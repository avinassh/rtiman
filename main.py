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
        rti_db = self.application.db.rti
        rti_doc = rti_db.find_one()
        credits = self.get_secure_cookie('credits', None)
        self.render('index.html', credits=credits, rti=rti_doc)          

class UserHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        username = self.get_secure_cookie('rtiman')
        credits = self.get_secure_cookie('credits')
        self.render('me.html', username=username, credits=credits)


class RTIDisplayHandler(BaseHandler):
    def get(self, rti_id):
        rti_db = self.application.db.rti        
        rti_doc = rti_db.find_one({'_id': ObjectId(rti_id)})
        credits = self.get_secure_cookie('credits', None)
        self.render('rti.html', rti_doc = rti_doc, credits=credits)


class AllRTIHandler(BaseHandler):
    def get(self):
        rti_db = self.application.db.rti
        rtis = list(rti_db.find({}))
        credits = self.get_secure_cookie('credits', None)
        self.render('rtis.html', rtis=rtis, credits=credits)

class FundRTIHandler(BaseHandler):
    @tornado.web.authenticated    
    def get(self, rti_id):
        credits = self.get_secure_cookie('credits', None)
        user_db = self.application.db.users    
        username = self.get_secure_cookie('rtiman')
        user_doc = user_db.find_one({'username': username})
        rti_db = self.application.db.rti
        rti_doc = rti_db.find_one({'_id': ObjectId(rti_id)})

        if not rti_doc:
            self.write('You are trying to fund an non existant RTI #FML')
            return

        self.render('fund.html', rti_doc=rti_doc, user_doc=user_doc, credits=credits)

    def post(self, rti_id):
        credits = self.get_argument('credits', None)
        rti_db = self.application.db.rti
        user_db = self.application.db.users    
        username = self.get_secure_cookie('rtiman')
        user_doc = user_db.find_one({'username': username})
        rti_doc = rti_db.find_one({'_id': ObjectId(rti_id)})

        if not credits:
            self.write('Please enter how much you want to fund')
            return

        try:
            credits = int(credits)
        except ValueError:
            self.write('Enter credits in numbers')
            return

        if credits > user_doc['credits']:
            self.write('You cannot fund more than credits you have. Please buy credits')
            return

        rti_doc['funds'] += credits
        user_doc['credits'] -= credits

        user_db.save(user_doc)
        rti_db.save(rti_doc)

        self.set_secure_cookie('credits', str(user_doc['credits']))
        self.redirect('/rti/%s' % rti_id)

class NewRTIHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        credits = self.get_secure_cookie('credits', None)
        self.render('newrti.html', credits=credits)

    def post(self):
        rti_name = self.get_argument('rti-name', None)
        rti_summary = self.get_argument('rti-text', None)
        rti_db = self.application.db.rti
        rti_id = str(rti_db.insert({'rti_name': rti_name, 'rti_summary': rti_summary, 'funds': 0}))

        self.redirect('/rti/%s' % rti_id)


class LoginHandler(BaseHandler):
    def get(self):
        self.render('login.html')

    def post(self):
        username = self.get_argument('username', None)
        password = self.get_argument('password', None)
        passwordhash = hashlib.sha512(password).hexdigest()
        user_db = self.application.db.users
        user_doc = user_db.find_one({'username': username})

        if not user_doc:
            self.write("You are not registered yet! <a href='/signup'>Signup</a> now!")
            return
            
        if user_doc['password'] != passwordhash:
            self.write("Invalid password, <a href='/login'>try</a> again")
            return

        # login successful
        credits = str(user_doc.get('credits', None))
        self.set_secure_cookie('rtiman', username)
        self.set_secure_cookie('credits', credits)    
        self.redirect('/')


class SignupHandler(BaseHandler):
    def get(self):
        self.render('signup.html')

    def post(self):
        username = self.get_argument('username', None)
        password = self.get_argument('password', None)
        passwordhash = hashlib.sha512(password).hexdigest()
        user_db = self.application.db.users

        try:                
            user_db.insert({'username': username, 'password': passwordhash, 
                'credits': 100})
        except pymongo.errors.DuplicateKeyError:
            self.write("Username already exists! <a href='/signup'>Try</a> again!")
            return

        # login successful
        self.set_secure_cookie('rtiman', username)
        self.set_secure_cookie('credits', '100')    
        self.redirect('/')

class LogoutHandler(BaseHandler):
    def get(self):
        self.clear_all_cookies()
        self.redirect('/')


def main():
    tornado.options.parse_command_line()
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    tornado.ioloop.IOLoop.instance().start()


if __name__ == "__main__":
    main()
