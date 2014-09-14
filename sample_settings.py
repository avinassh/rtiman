# all the settings, auth etc.

import os

MONGO_URL = "mongodb://avinassh:avinassh@localhost:10031/rti"

application_handler_setttings = dict(
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=os.path.join(os.path.dirname(__file__), "static"),
            cookie_secret= 'aV1..No5h',
            login_url='/login',
            debug=True,
            )