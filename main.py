#!/usr/bin/env python

import datetime
import os.path # for template and static files
import json
import hashlib # for passwords
from bson.objectid import ObjectId
from bson.json_util import dumps

# bunch of Tornado imports
import tornado.auth
import tornado.escape
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
from tornado import gen
from tornado.options import define, options

import pymongo
from pymongo import MongoClient

#uses https://github.com/joerussbowman/tornado_flash
import tornado_flash

import settings
from settings import MONGO_URL

define("port", default=8000, help="run on the given port", type=int)

# put your mongodb username and password 
# "mongodb://username:password@staff.mongohq.com:someport/mongodb_name"
# following is obtained from https://app.mongohq.com/username/mongo/mongodbname/admin
# MONGOHQ_URL = "mongodb://avi:password@staff.mongohq.com:27017/trackr"


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r'/', MainHandler),
            (r'/login', LoginHandler),
            (r'/logout', LogoutHandler),
            (r'/signup', SignupHandler),
            (r'/rti', AllRTIHandler), # post to submit a new rti
            (r'/rti/new', NewRTIHandler),
            (r'/rti/fund/(\w+)', FundRTIHandler),
            (r'/rti/(\w+)', RTIDisplayHandler), # post to receive funds
            (r'/me', UserHandler),
        ]
        app_settings = settings.application_handler_setttings
        conn = pymongo.MongoClient(MONGO_URL)
        self.db = conn["rti"]
        tornado.web.Application.__init__(self, handlers, **app_settings)


class BaseHandler(tornado.web.RequestHandler):
    def get_current_user(self):
        return bool(self.get_secure_cookie('rtiman'))


class MainHandler(BaseHandler):
    def get(self):
        flash = tornado_flash.Flash(self)
        rti_db = self.application.db.rti
        rti_doc = rti_db.find_one()
        credits = self.get_secure_cookie('credits', None)
        self.render('index.html', credits=credits, rti=rti_doc, flash=flash)          

class UserHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        flash = tornado_flash.Flash(self)
        username = self.get_secure_cookie('rtiman')
        credits = self.get_secure_cookie('credits')
        self.render('me.html', username=username, credits=credits, flash=flash)


class RTIDisplayHandler(BaseHandler):
    def get(self, rti_id):
        flash = tornado_flash.Flash(self)
        rti_db = self.application.db.rti        
        rti_doc = rti_db.find_one({'_id': ObjectId(rti_id)})
        credits = self.get_secure_cookie('credits', None)
        self.render('rti.html', rti_doc = rti_doc, credits=credits, flash=flash)


class AllRTIHandler(BaseHandler):
    def get(self):
        flash = tornado_flash.Flash(self)
        rti_db = self.application.db.rti
        rtis = list(rti_db.find({}))
        credits = self.get_secure_cookie('credits', None)
        self.render('rtis.html', rtis=rtis, credits=credits, flash=flash)

class FundRTIHandler(BaseHandler):
    @tornado.web.authenticated    
    def get(self, rti_id):
        flash = tornado_flash.Flash(self)
        credits = self.get_secure_cookie('credits', None)
        user_db = self.application.db.users    
        username = self.get_secure_cookie('rtiman')
        user_doc = user_db.find_one({'username': username})
        rti_db = self.application.db.rti
        rti_doc = rti_db.find_one({'_id': ObjectId(rti_id)})

        if not rti_doc:
            flash.data = {"class": "warning", "msg": 'You are trying to fund an non existent RTI #FML'}
            self.redirect('/rti')
            return

        self.render('fund.html', rti_doc=rti_doc, user_doc=user_doc, credits=credits, flash=flash)

    def post(self, rti_id):
        flash = tornado_flash.Flash(self)
        credits = self.get_argument('credits', None)
        password = self.get_argument('password', None)
        passwordhash = hashlib.sha512(password).hexdigest()
        rti_db = self.application.db.rti
        user_db = self.application.db.users    
        username = self.get_secure_cookie('rtiman')
        user_doc = user_db.find_one({'username': username})
        rti_doc = rti_db.find_one({'_id': ObjectId(rti_id)})

        if not credits:
            flash.data = {"class": "warning", "msg": 'Incorrect credit entered'}
            self.redirect(self.request.uri)            
            return

        try:
            credits = int(credits)
        except ValueError:
            flash.data = {"class": "warning", "msg": 'Incorrect credit entered'}
            self.redirect(self.request.uri)            
            return

        if user_doc['password'] != passwordhash:
            flash = tornado_flash.Flash(self)
            flash.data = {"class": "danger", "msg": "Incorrect password"}
            self.redirect(self.request.uri)
            return

        if credits > user_doc['credits']:
            flash.data = {"class": "warning", "msg": 'You cannot fund more than credits you have. Please buy credits.'}
            self.redirect(self.request.uri)            
            return

        if credits < 9:
            flash.data = {"class": "warning", "msg": 'Minimum fund value is 10.'}
            self.redirect(self.request.uri)            
            return        

        rti_doc['funds'] += credits
        user_doc['credits'] -= credits

        user_db.save(user_doc)
        rti_db.save(rti_doc)

        flash.data = {"class": "success", "msg": 'RTI funded successfully :-)'}
        self.set_secure_cookie('credits', str(user_doc['credits']))
        self.redirect('/rti/%s' % rti_id)

class NewRTIHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        flash = tornado_flash.Flash(self)
        credits = self.get_secure_cookie('credits', None)
        self.render('newrti.html', credits=credits, flash=flash)

    def post(self):
        flash = tornado_flash.Flash(self)
        rti_name = self.get_argument('rti-name', None)
        rti_summary = self.get_argument('rti-text', None)
        rti_db = self.application.db.rti
        rti_id = str(rti_db.insert({'rti_name': rti_name, 'rti_summary': rti_summary, 'funds': 0}))
        flash.data = {"class": "info", "msg": "RTI query request submitted successfully. Share it in social media."} 
        self.redirect('/rti/%s' % rti_id)


class LoginHandler(BaseHandler):
    def get(self):
        flash = tornado_flash.Flash(self)
        if self.get_current_user():
            flash.data = {"class": "warning", "msg": "You are already logged in!"}
            self.redirect('/')
            return
        self.render('login.html', flash=flash)

    def post(self):
        flash = tornado_flash.Flash(self)
        username = self.get_argument('username', None)
        password = self.get_argument('password', None)
        passwordhash = hashlib.sha512(password).hexdigest()
        user_db = self.application.db.users
        user_doc = user_db.find_one({'username': username})

        if not user_doc:
            flash.data = {"class": "warning", "msg": "Username not found, may be you wanted to register?"} 
            self.redirect('/signup')
            return
            
        if user_doc['password'] != passwordhash:
            flash.data = {"class": "danger", "msg": "Invalid password!"} 
            self.redirect('/login')
            return

        # login successful
        credits = str(user_doc.get('credits', None))
        self.set_secure_cookie('rtiman', username)
        self.set_secure_cookie('credits', credits)
        flash.data = {"class": "success", "msg": "Login successful!"}    
        self.redirect('/')


class SignupHandler(BaseHandler):
    def get(self):
        flash = tornado_flash.Flash(self)
        if self.get_current_user():
            flash.data = {"class": "warning", "msg": "You are already logged in!"}
            self.redirect('/')
            return

        self.render('signup.html', flash=flash)

    def post(self):
        flash = tornado_flash.Flash(self)
        username = self.get_argument('username', None)
        password = self.get_argument('password', None)
        passwordhash = hashlib.sha512(password).hexdigest()
        user_db = self.application.db.users

        try:                
            user_db.insert({'username': username, 'password': passwordhash, 
                'credits': 100})
        except pymongo.errors.DuplicateKeyError:
            flash.data = {"class": "danger", "msg": "Username already exists!"}
            self.redirect('/signup')  
            return

        # login successful
        flash.data = {"class": "success", "msg": "Signup successful, Welcome to RTI Man!"}
        self.set_secure_cookie('rtiman', username)
        self.set_secure_cookie('credits', '100')    
        self.redirect('/')

class LogoutHandler(BaseHandler):
    def get(self):
        flash = tornado_flash.Flash(self)
        flash.data = {"class": "success", "msg": "Bye Bye, Have a nice day!"}
        self.clear_all_cookies()
        self.redirect('/')


def main():
    tornado.options.parse_command_line()
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    tornado.ioloop.IOLoop.instance().start()


if __name__ == "__main__":
    main()
