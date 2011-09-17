#!/usr/bin/python

import cgi
import logging
import urllib2

from django.utils import simplejson

from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

import os
from google.appengine.ext.webapp import template
import datetime

# config data
config = {'server' : 'https://foursquare.com',
          'api_server' : 'https://api.foursquare.com',
          'redirect_uri' : 'https://welcometo4sq.appspot.com',
          'client_id' : '[YOUR CLIENT ID]',
          'client_secret' : '[YOUR CLIENT SECRET]',
          'target_venue' : '[THE VENUE ID YOU WANT TO TARGET (mongo-style)]'}


# PUSH HANDLER
# Catches the actual push and stores it in the datastore
# *** THIS IS WHERE THE MAGIC HAPPENS ***
class ReceiveHereNow(webapp.RequestHandler):
  def post(self):
    # Load the checkin parameter. As specified by the push api.
    checkin_json = simplejson.loads(self.request.get('checkin'))
    # Get user and venue out of the checkin
    user_id = checkin_json['user']['id']
    venue_id = checkin_json['venue']['id']
    # Only save the checkins for the target venue
    if (venue_id == config['target_venue']):
      checkin = Checkin()
      checkin.fs_id = user_id
      checkin.checkin_json = simplejson.dumps(checkin_json)
      checkin.venue_id = venue_id
      checkin.put()
    else:
      logging.warning("Received a checkin for another venue: " + venue_id + "\n" + simplejson.dumps(checkin_json))

# OAUTH HANDLERS
# Start the OAuth loop with foursquare.
class OAuthStart(webapp.RequestHandler):
  def get(self):
    url = '%(server)s/oauth2/authenticate?client_id=%(client_id)s&response_type=token&redirect_uri=%(redirect_uri)s' % config
    self.redirect(url)

# Handle the OAuth AJAX save call.
class OAuthLanding(webapp.RequestHandler):
  def post(self):
    self.get()

  def get(self):
    token = UserToken()
    token.token = self.request.get("access_token")
    token.user = users.get_current_user()

    self_response = fetchJson('%s/v2/users/self?oauth_token=%s' % (config['api_server'], token.token))
    if (self_response['meta']['code'] == 200) :
      token.fs_id = self_response['response']['user']['id']
      token.put()

    self.redirect("/")

# DATASTORE ACCESS HANDLERS
# Fetch the checkins we've received via push.
class FetchCheckins(webapp.RequestHandler):
  def get(self):
    checkins = Checkin.all().order('-timestamp').fetch(100)
    ret = [c.checkin_json for c in checkins]
    self.response.out.write('['+ (','.join(ret)) +']')

# Fetch the herenow data fresh from foursquare
class FetchHereNow(webapp.RequestHandler):
  def get(self):
    user = UserToken.all().filter("user = ", users.get_current_user()).get()
    if (user is None):
      ret = {'authed': False}
      self.response.out.write(simplejson.dumps(ret))
    else:
      json = fetchJson('%s/v2/venues/%s/herenow?oauth_token=%s' % (config['api_server'], config['target_venue'], user.token))
      mayorjson = fetchJson('%s/v2/venues/%s?oauth_token=%s' % (config['api_server'], config['target_venue'], user.token))

      mayorID = mayorjson['response']['venue']['mayor']['user']['id']

      hereNow = json['response']['hereNow']
      people = []
      mayor = {'ishere' : False}
      for checkin in hereNow['items']:
        if (mayorID == checkin['user']['id']):
          mayor['ishere'] = True
          mayor['photo'] = checkin['user']['photo']
          mayor['firstName'] = checkin['user']['firstName']
          if 'lastName' in checkin['user']:
            mayor['lastName'] = checkin['user']['lastName']
            mayor['lastName'] =  mayor['lastName'][0:1] + "."
          else:
            mayor['lastName'] =  " "
        else:
          person = {}
          person['photo'] = checkin['user']['photo']
          person['firstName'] = checkin['user']['firstName']
          if 'lastName' in checkin['user']:
            person['lastName'] = checkin['user']['lastName']
            person['lastName'] =  person['lastName'][0:1] + "."
          else:
            person['lastName'] =  " "
          people.append(person)
      ret = {'authed': True, 'count': hereNow['count'], 'people': people, 'mayor': mayor}
      
      self.response.out.write(simplejson.dumps(ret))

# MODELS
# Contains the user to foursquare_id + oauth token mapping.
class UserToken(db.Model):
  user = db.UserProperty()
  fs_id = db.StringProperty()
  token = db.StringProperty()

# A very simple checkin object, with a denormalized userid for querying.
class Checkin(db.Model):
  timestamp = db.DateTimeProperty(auto_now_add=True)
  fs_id = db.StringProperty()
  checkin_json = db.TextProperty()

# UTILITY FUNCTIONS
# Does a GET to the specified URL and returns a dict representing its reply.
def fetchJson(url):
  logging.info('fetching url: ' + url)
  try :
    result = urllib2.urlopen(url).read()
    logging.info('got back: ' + result)
    return simplejson.loads(result)
  except urllib2.URLError, e :
    logging.error(e)

# RENDERING HELPERS
# Return the render for a checkin
class ajaxCheckin(webapp.RequestHandler):
    def get(self):
      doRender(self, 'checkin.html')

# A helper to do the rendering and to add the necessary
# variables for the _base.htm template
def doRender(handler, tname = 'index.htm', values = { }):
  temp = os.path.join(
      os.path.dirname(__file__),
      'templates/' + tname)
  if not os.path.isfile(temp):
    return False

  # Make a copy of the dictionary and add the path and session
  newval = dict(values)
  newval['path'] = handler.request.path
  outstr = template.render(temp, newval)
  handler.response.out.write(outstr)
  return True
  
# Set up the handlers
application = webapp.WSGIApplication([('/login', OAuthStart),
                                      ('/oauth', OAuthLanding), 
                                      ('/herenow', ReceiveHereNow),
                                      ('/fetch', FetchCheckins),
                                      ('/checkin', ajaxCheckin),
                                      ('/fetchherenow', FetchHereNow)],
                                     debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
