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

# prod
config = {'server':'https://foursquare.com',
          'api_server':'https://api.foursquare.com',
          'redirect_uri': 'https://welcometo4sq.appspot.com/oauth',
          'client_id': '[YOUR ID!]',
          'client_secret': '[YOUR SECRET!]'}

class UserToken(db.Model):
  """Contains the user to foursquare_id + oauth token mapping."""
  user = db.UserProperty()
  fs_id = db.StringProperty()
  token = db.StringProperty()

class Checkin(db.Model):
  """A very simple checkin object, with a denormalized userid for querying."""
  timestamp = db.DateTimeProperty(auto_now_add=True)
  fs_id = db.StringProperty()
  checkin_json = db.TextProperty()

def fetchJson(url, dobasicauth = False):
  """Does a GET to the specified URL and returns a dict representing its reply."""
  logging.info('fetching url: ' + url)
  result = urllib2.urlopen(url).read()
  logging.info('got back: ' + result)
  return simplejson.loads(result)

class OAuth(webapp.RequestHandler):
  """Handle the OAuth redirect back to the service."""
  def post(self):
    self.get()

  def get(self):
    code = self.request.get('code')
    args = dict(config)
    args['code'] = code
    url = ('%(server)s/oauth2/access_token?client_id=%(client_id)s&client_secret=%(client_secret)s&grant_type=authorization_code&redirect_uri=%(redirect_uri)s&code=%(code)s' % args)
  
    json = fetchJson(url, config['server'].find('staging.foursquare.com') != 1)

    token = UserToken()
    token.token = json['access_token']
    token.user = users.get_current_user()

    self_response = fetchJson('%s/v2/users/self?oauth_token=%s' % (config['api_server'], token.token))

    token.fs_id = self_response['response']['user']['id']
    token.put()

    self.redirect("/")

class ReceiveHereNow(webapp.RequestHandler):
  """Received a pushed checkin and store it in the datastore."""
  def post(self):
    checkin_json = simplejson.loads(self.request.get('checkin'))
    user_json = checkin_json['user']
    checkin = Checkin()
    checkin.fs_id = user_json['id']
    checkin.checkin_json = simplejson.dumps(checkin_json)
    checkin.venue_id = checkin_json['venue']['id']
    checkin.put()

class FetchCheckins(webapp.RequestHandler):
  """Fetch the checkins we've received via push for the current user."""
  def get(self):
    checkins = Checkin.all().order('-timestamp').fetch(100)
    ret = [c.checkin_json for c in checkins]
    self.response.out.write('['+ (','.join(ret)) +']')

class FetchHereNow(webapp.RequestHandler):
  def get(self):
    
    ######### DANGER! this empties the datastore ##############
    # query = db.GqlQuery("SELECT * FROM Checkin")
    # for q in query:
    #   db.delete(q)
    ###########################################################
    
    user = UserToken.all().filter("user = ", users.get_current_user()).get()
    vid = self.request.get('vid')
    json = fetchJson('%s/v2/venues/%s/herenow?oauth_token=%s' % (config['api_server'], vid, user.token))
    mayorjson = fetchJson('%s/v2/venues/%s?oauth_token=%s' % (config['api_server'], vid, user.token))

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
    ret = {'count': hereNow['count'], 'people': people, 'mayor': mayor}
    
    self.response.out.write(simplejson.dumps(ret))

class GetConfig(webapp.RequestHandler):
  """Returns the OAuth URI as JSON so the constants aren't in two places."""
  def get(self):
    uri = '%(server)s/oauth2/authenticate?client_id=%(client_id)s&response_type=code&redirect_uri=%(redirect_uri)s' % config
    self.response.out.write(simplejson.dumps({'auth_uri': uri}))

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
  
application = webapp.WSGIApplication([('/oauth', OAuth), 
                                      ('/herenow', ReceiveHereNow),
                                      ('/fetch', FetchCheckins),
                                      ('/config', GetConfig),
                                      ('/checkin', ajaxCheckin),
                                      ('/fetchherenow', FetchHereNow)],
                                     debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
