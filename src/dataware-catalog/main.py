from __future__ import division
import json
import urllib
import OpenIDManager
from CatalogDB import *   
import logging
import AuthorizationModule
import wsgiref.util
from framework import bottle
from framework.bottle import *

from os.path import join, dirname

log = logging.getLogger( "console_log" )

@route( "/", method = "GET" )
@route( "/home", method = "GET" )
def user_home( ):
    try:
        user = _user_check_login()  
    except RegisterException, e:
        redirect( "/register" )
    except LoginException, e:
        return user_error( e.msg )
    except Exception, e:
        return user_error( e )
   
    #redirect("/audit")
    resources = None
    if user:
        resources = db.resources_fetch_by_user( user['user_id'] )
    return template( "home_page_template", REALM=REALM, user=user, resources=resources);

#///////////////////////////////////////////////


@route( "/login", method = "GET" )
def user_openid_login():

    try:
        params = "resource_id=%s&redirect_uri=%s&state=%s" % \
            ( request.GET[ "resource_id" ],
              request.GET[ "redirect_uri" ], 
              request.GET[ "state" ], )
    except:
        params = ""
    
    try: 
        username = request.GET[ "username" ]    
    except: 
        username = None
     
    try:      
        provider = request.GET[ "provider" ]
    except: 
        return template( 
            "login_page_template", 
            REALM=REALM, user=None, params=params )    
    try:
        url = OpenIDManager.process(
            realm=REALM,
            return_to=REALM + "/checkauth?" + urllib.quote( params ),
            provider=provider,
            username=username,
            web_proxy=WEB_PROXY
        )
    except Exception, e:
        log.error( e )
        return user_error( e )
    
   
    #Here we do a javascript redirect. A 302 redirect won't work
    #if the calling page is within a frame (due to the requirements
    #of some openid providers who forbid frame embedding), and the 
    #template engine does some odd url encoding that causes problems.
    return "<script>self.parent.location = '%s'</script>" % (url,)
    

#///////////////////////////////////////////////

@route( "/logout" )
def user_openid_logout():
    
    _delete_authentication_cookie()
    redirect( ROOT_PAGE )

#///////////////////////////////////////////////    
    
@route( "/register", method = "GET" )
def user_register():
    
    #TODO: first check the user is logged in!
    try:
        user_id = _user_extract_id()
    except LoginException, e:
        return user_error( e.msg )
    except Exception, e:
        return user_error( e )
    
    errors = {}
    
    #if the user has submitted registration info, parse it
    try: 
        request.GET[ "submission" ]
        submission = True;
    except:
        submission = False

    if ( submission ): 

        #validate the user_name supplied by the user
        try:
            user_name = request.GET[ "user_name" ]
            email = request.GET[ "email" ]
            if ( not _valid_name( user_name ) ):
                errors[ 'user_name' ] = "Must be 3-64 legal characters"
            else: 
                match = db.user_fetch_by_name( user_name ) 
                if ( not match is None ):
                    errors[ 'user_name' ] = "That name has already been taken"                    
        except:
            errors[ 'user_name' ] = "You must supply a valid user name"

    
        #validate the email address supplied by the user
        try:
            email = request.GET[ "email" ]

            if ( not _valid_email( email ) ):
                errors[ 'email' ] = "The supplied email address is invalid"
            else: 
                match = db.user_fetch_by_email( email ) 
                if ( not match is None ):
                    errors[ 'email' ] = "That email has already been taken"
        except:
            errors[ 'email' ] = "You must supply a valid email"

        #if everything is okay so far, add the data to the database    
        if ( len( errors ) == 0 ):
	    try:
  	    	match= db.user_register(user_id, user_name, email)
	    	db.commit()
	    except Exception, e:
		return user_error(e)

	    #update the cookie with the new details
            _set_authentication_cookie( user_id, user_name )
              
            #return the user to the user_home page
            redirect( ROOT_PAGE )
    
    else:
        email = ""
        user_name = ""
        
    #if this is the first visit to the page, or there are errors

    return template( 
        "register_page_template",
        REALM=REALM,  
        user=None, 
        email=email,
        user_name=user_name,
        errors=errors ) 
    


#//////////////////////////////////////////////////////////
# CATALOG SPECIFIC WEB-API CALLS
#//////////////////////////////////////////////////////////

   
#TODO: make sure that redirect uri's don't have a / on the end


@route("/refreshtoken", method="GET")
def refreshtoken():
    try:
        user = _user_check_login()
    except RegisterException, e:
        redirect( "/register" ) 
    except LoginException, e:
        return user_error( e.msg )
    except Exception, e:
        return user_error( e ) 
    return json.dumps({'token':'none'})
    #token = channel.create_channel(user.email)
    #log.info("recreated channel token %s" % token)            
    #db.user_update_token(user.user_id, token) 
    #log.info("updated user token");
    #return json.dumps({'token':token});
    
@route("/sendmessage", method="POST")
def sendmessage():
    try:
        user = _user_check_login()
    except RegisterException, e:
        redirect( "/register" ) 
    except LoginException, e:
        return user_error( e.msg )
    except Exception, e:
        return user_error( e ) 
    
    log.info("sending a message!")
    
    #token = channel.send_message(user.email, "hello!!!")
    
    log.info("finshed sending a message!")

@route( "/resource_register", method = "POST" )
@route( "/user/:user_name/resource_register", method = "GET" )
def resource_register_endpoint():
    
    resource_name = request.forms.get( "resource_name" )   
    resource_uri = request.forms.get( "redirect_uri" )
    description = request.forms.get( "description" )
    logo_uri = request.forms.get( "logo_uri" )
    web_uri = request.forms.get( "web_uri" )
    namespace = request.forms.get( "namespace" )
    
    log.debug("name space is %s" % namespace)
    
    result = am.resource_register( 
        resource_name = resource_name,
        resource_uri = resource_uri,
        description = description,
        logo_uri = logo_uri,
        web_uri = web_uri,
        namespace = namespace,
    )
    
    log.debug( 
        "Catalog_server: Resource Registration for client '%s': %s" 
        % ( resource_name, result ) 
    )
        
    return result    
    
    
#//////////////////////////////////////////////////////////


@route( "/resource_request", method = "GET" )
@route( "/user/:user_name/resource_request", method = "GET" )
def resource_request_endpoint():

    #first check that required parameters have beeing supplied
    try: 
        resource_id = request.GET[ "resource_id" ]
        resource_uri = request.GET[ "redirect_uri" ]
        state = request.GET[ "state" ]
    except:
        return template( 'resource_request_error_template', 
           error = "The resource has not supplied the right parameters." 
        );

    #Then check that the resource has registered
    #here the resource id is the resource's datastore Key rather 
    #than the resource_id attribute, as querying on the attribute 
    #is eventually consistent. fetch the object by its key is
    #strongly consistent.
    
    log.info("fetching resource by id %s" % resource_id)
    
    resource = db.resource_fetch_by_id( resource_id ) 
    
    if ( not resource ):
        return template( 'resource_request_error_template', 
           error = "Resource isn't registered with us, so cannot install."
        );
   
    log.info("resource.resource_uri is %s and resource_uri is %s" % (resource['resource_uri'], resource_uri)) 
    #And finally check that it has supplied the correct credentials
    if ( resource['resource_uri'] != resource_uri ):
        return template( 'resource_request_error_template', 
           error = "The resource has supplied incorrect credentials."
        );

    try:
        user = _user_check_login()
    except RegisterException, e:
        redirect( "/register" ) 
    except LoginException, e:
        return user_error( e.msg )
    except Exception, e:
        return user_error( e ) 
    
    if (user is None):
        return template( 'resource_request_error_template', 
           error = "Please make sure you are logged into your catalog!"
        );
        
    return template( 'resource_request_template', 
        user=user,
        state=state,
        resource=resource
    );


#//////////////////////////////////////////////////////////
 

@route( "/resource_authorize", method = "POST" )
@route( "/user/:user_name/resource_authorize", method = "GET" )
def resource_authorize_endpoint():
    
    try:
        user = _user_check_login()
    except RegisterException, e:
        redirect( "/register" ) 
    except LoginException, e:
        return user_error( e.msg )
    except Exception, e:
        return user_error( e ) 
    
    resource_id = request.forms.get( "resource_id" )   
    resource_uri = request.forms.get( "redirect_uri" )
    state = request.forms.get( "state" )  
    
    log.info("resource id is %s" % resource_id)
    log.info("resource uri us %s" % resource_uri)
    log.info("state is %s " % state)
    
    result = am.resource_authorize( 
        user,
        resource_id = resource_id,
        resource_uri = resource_uri,
        state = state,
    )
   
    log.debug( 
        "Catalog_server: Resource Authorization Request from %s for %s completed" 
        % ( user['user_id'], resource_id ) 
    )

    return result


#//////////////////////////////////////////////////////////
      

@route( "/resource_access", method = "GET" )
@route( "/user/:user_name/resource_authorize", method = "GET" )
def resource_access_endpoint():

    grant_type = request.GET.get( "grant_type", None )
    resource_uri = request.GET.get( "redirect_uri", None )
    auth_code = request.GET.get( "code", None )    
                
    result = am.resource_access( 
        grant_type = grant_type,
        resource_uri = resource_uri,
        auth_code = auth_code 
    )

    return result


#//////////////////////////////////////////////////////////

#//////////////////////////////////////////////////////////

@route( "/resource/<resource>/user/<user>", method = "GET" )
def resource_details(resource, user):
  
    resource =  db.resource_fetch_by_user(resource,user)
    log.debug("got here..")
    if resource is not None:
	    return json.dumps(resource)
    return "nowt!"

@route( "/client_register", method = "POST" )
def client_register_endpoint():
    
    client_name = request.forms.get( "client_name" )   
    namespace = request.forms.get( "namespace" )
    client_uri = request.forms.get( "redirect_uri" )
    description = request.forms.get( "description" )
    logo_uri = request.forms.get( "logo_uri" )
    web_uri = request.forms.get( "web_uri" )
    
        
    result = am.client_register( 
        client_name = client_name,
        client_uri = client_uri,
        description = description,
        logo_uri = logo_uri,
        web_uri = web_uri,
        namespace = namespace,
    )
    
    log.debug( 
        "Catalog_server: Client Registration for client '%s': %s" 
        % ( client_name, result ) 
    )
        
    return result    
    
    
#//////////////////////////////////////////////////////////

    
@route( "/user/:user_name/client_request", method = "POST" )
def client_request_endpoint( user_name = None ):

    client_id = request.forms.get( "client_id" )
    state = request.forms.get( "state" )
    client_uri = request.forms.get( "redirect_uri" )
    json_scope = request.forms.get( "scope" )

    log.info("client request endpoint %s %s %s" % (client_id, state, client_uri))
    
    result = am.client_request( 
        user_name = user_name,
        client_id = client_id,
        state = state,
        client_uri = client_uri,
        json_scope = json_scope 
    )
 
    log.debug( 
        "Catalog_server: Client Request from %s to %s: %s" 
        % ( client_id, user_name, result ) 
    )
       
    return result


   
#//////////////////////////////////////////////////////////
 

@route( "/client_authorize", method = "POST" )
def client_authorize_endpoint():

    #by this point the user has authenticated and will have
    #a cookie identifying themselves, and this is used to extract
    #their id. This will be an openid (working as an access key),
    #even though they have a publically exposed username. This
    #api call involves interaction via the user's web agent so
    #will redirect the user to the client if the access request
    #acceptance is successful, or display an appropriate user_error page
    #otherwise (e.g. if the resource provider rejects the request.

    try:
        user = _user_check_login()
    except RegisterException, e:
        redirect( "/register" ) 
    except LoginException, e:
        return user_error( e.msg )
    except Exception, e:
        return user_error( e ) 
    
    processor_id = request.forms.get( 'processor_id' )

    log.info("processor id is %s" % processor_id)
    
    result = am.client_authorize( 
        user_id = user['user_id'],
        processor_id = processor_id,
    )
    
    log.debug( 
        "Catalog_server: Authorization Request from %s for request %s completed" 
        % ( user['user_id'], processor_id ) 
    )

    return result


#//////////////////////////////////////////////////////////   
      

@route( "/client_reject", method = "POST" )
def client_reject_endpoint():
    
    try:
        user = _user_check_login()
    except RegisterException, e:
        redirect( "/register" ) 
    except LoginException, e:
        return user_error( e.msg )
    except Exception, e:
        return user_error( e ) 
    
    processor_id = request.forms.get( 'processor_id' )
    
    result = am.client_reject( 
        user_id =  user['user_id'],
        processor_id = processor_id,
    )

    log.debug( 
        "Catalog_server: Request rejection from %s for request %s" 
        % ( user['user_id'], processor_id ) 
    )

    return result

    
#//////////////////////////////////////////////////////////

@route( "/client_list_resources", method = "GET" )      
def client_list_resources():
    
    client_id = request.GET.get( "client_id", None )
    client_uri = request.GET.get( "client_uri", None )
    log.info("got client_id: %s client_uri: %s" % (client_id, client_uri))
    
    if am.client_registered(client_id=client_id, client_uri=client_uri):
        log.info("client is registered!!")
        
        resource_owner =  request.GET.get( "resource_owner", None )
        resource_name = request.GET.get( "resource_name", None )
       
        result = json.dumps(db.resource_registered(wsgiref.util.application_uri(request.environ)[:-1], resource_owner, resource_name))
        log.info(result)
        return result
    
    log.info("hmmm client is not registered %s %s" % (client_id, client_uri))
    
    return "{'error': 'client not registered with this catalog!'}"

#//////////////////////////////////////////////////////////
@route( "/client_access", method = "GET" )
def client_access_endpoint():

    grant_type = request.GET.get( "grant_type", None )
    client_uri = request.GET.get( "redirect_uri", None )
    auth_code = request.GET.get( "code", None )    
    log.info("doing a client access for access code %s" % auth_code)
     
    result = am.client_access( 
        grant_type = grant_type,
        client_uri = client_uri,
        auth_code = auth_code 
    )
    
    return result

    
#//////////////////////////////////////////////////////////   


@route( "/client_revoke", method = "POST" )
def client_revoke_enpdpoint():
    
    try:
        user = _user_check_login()
    except RegisterException, e:
        redirect( "/register" ) 
    except LoginException, e:
        return user_error( e.msg )
    except Exception, e:
        return user_error( e ) 
    
    processor_id = request.forms.get( "processor_id" )

    result = am.client_revoke( 
        user_id =  user['user_id'],
        processor_id = processor_id,
    )

    log.debug( 
        "Catalog_server: Request %s has been successfully revoked by %s" \
         % ( processor_id,  user['user_id']) 
    )
    
    return result
                        
@route("/test_query", method="POST")
def test_query():
    
    resource_uri = request.forms.get( 'resource_uri' )
    query = request.forms.get('query')
    parameters = request.forms.get('parameters')
    
    result = am.test_query( 
        resource_uri =  resource_uri,
        query = query,
        parameters = parameters
    )
     
    
@route( "/static/:filename" )
def user_get_static_file( filename ):
    return static_file( filename, root=os.path.join(ROOT_PATH, 'static'))

@route( "/static/:path#.+#" )

def user_get_static_file( path ):
    return static_file( path, root=os.path.join(ROOT_PATH, 'static'))

 
 
#//////////////////////////////////////////////////////////
# OPENID SPECIFIC WEB-API CALLS
#//////////////////////////////////////////////////////////


class LoginException ( Exception ):
    
    def __init__(self, msg):
        self.msg = msg


#///////////////////////////////////////////////


class RegisterException ( Exception ):
    """Base class for RegisterException in this module."""
    
    pass

    
#///////////////////////////////////////////////

#///////////////////////////////////////////////


@route( "/error", method = "GET" )
def user_error( e ):
    
    return "A user_error has occurred: %s" % ( e )


#///////////////////////////////////////////////
    
#///////////////////////////////////////////////

    
def _user_check_login():

    #first try and extract the user_id from the cookie.
    #n.b. this can generate LoginExceptions
    user_id = _user_extract_id()

    if ( user_id ) :
        
        #we should have a record of this id, from when it was authenticated
        user = db.user_fetch_by_id( user_id )
        
        if ( not user ):
            _delete_authentication_cookie()
            raise LoginException( "We have no record of the id supplied. Resetting." )
        
        #and finally lets check to see if the user has registered their details
        if ( user['user_name'] is None):
            raise RegisterException()
        
        return user
        
    #if the user has made it this far, their page can be processed accordingly
    else:
        return None

def _user_extract_id():
    
    cookie = request.get_cookie( EXTENSION_COOKIE )
        
    #is the user logged in? First check we have a cookie...
    if cookie:
        #and that it contains suitably formatted data
        try:
            data = json.loads( cookie )
        except:
            _delete_authentication_cookie()
            raise LoginException( "Your login data is corrupted. Resetting." )
        
        #and then that it contains a valid user_id
        try:
            user_id =  data[ "user_id" ]
            return user_id
        except:
            _delete_authentication_cookie()
            raise LoginException( "You are logged in but have no user_id. Resetting." )
    else:
        return None


     
     
     
#///////////////////////////////////////////////
 
         
def _delete_authentication_cookie():
    
    response.delete_cookie( 
        key=EXTENSION_COOKIE,
    )
            
            
#///////////////////////////////////////////////


def _set_authentication_cookie( user_id, user_name = None ):
    
    #if the user has no "user_name" it means that they
    #haven't registered an account yet    
    if ( not user_name ):
        json = '{"user_id":"%s","user_name":null}' \
            % ( user_id, )
        
    else:
        json = '{"user_id":"%s","user_name":"%s"}' \
            % ( user_id, user_name )
         
    response.set_cookie( EXTENSION_COOKIE, json )
    
    
#//////////////////////////////////////////////////////////

@route( "/checkauth", method = "GET" )
def user_openid_authenticate():
    
    o = OpenIDManager.Response( request.GET )
    
    #check to see if the user logged in succesfully
    if ( o.is_success() ):
        
        user_id = o.get_user_id()
         
        #if so check we received a viable claimed_id
        if user_id:
            try:
                user = db.user_fetch_by_id( user_id )
                 
                #if this is a new user add them
                if ( not user ):
                    db.user_insert( o.get_user_id() )
                    user_name = None
                else :
                    user_name = user['user_name']
                
                _set_authentication_cookie( user_id, user_name  )
                
            except Exception, e:
                return user_error( e )
            
            
        #if they don't something has gone horribly wrong, so mop up
        else:
            _delete_authentication_cookie()

    #else make sure the user is still logged out
    else:
        _delete_authentication_cookie()
        
    try:
        redirect_uri = "resource_request?resource_id=%s&redirect_uri=%s&state=%s" % \
            ( request.GET[ "resource_id" ], 
              request.GET[ "redirect_uri" ], 
              request.GET[ "state" ] )
    except:
        redirect_uri = REALM + ROOT_PAGE
    
    return "<script>self.parent.location = '%s'</script>" % ( redirect_uri, )
       
                
#///////////////////////////////////////////////
    
@route( "/audit" )
def user_audit():
    
    PREVIEW_ROWS = 10
    
    try:
        user = _user_check_login()
        if ( not user ) : redirect( ROOT_PAGE ) 
    except RegisterException, e:
        redirect( "/register" ) 
    except LoginException, e:
        return user_error( e.msg )
    except Exception, e:
        return user_error( e )  
    
    processors = db.processors_fetch( user['user_id'] )
    
    for processor in processors:
        try:
            index = [ m.start() for m in re.finditer( r"\n", processor['query']) ][ PREVIEW_ROWS ]
            processor['preview'] = "%s\n..." % processor['query'][ 0:index ]
        except:
            log.error('failed to create preview for processor!') 
            processor['preview'] = processor['query']
    
    log.debug("creating audit template for processors!");
    log.debug(processors)
    log.debug(json.dumps([p for p in processors]))
    
    fromPage = None
    if request.method == 'GET' and 'fromPage' in request.GET:
        fromPage = request.GET[ "fromPage" ]
        print "from page % s" % fromPage
        
    
    return template( 
        "audit_page_template", 
        REALM=REALM, 
        user=user, 
        processors=processors,
        fromPage=fromPage,
        processorjson=(json.dumps([p for p in processors]))
    );

@route( "/purge" )
def purge():    
    db.purgedata()
    redirect( "/" )
    
    
@route( "/reset" )
def reset():    
    db.resetdata()
    return "{'success':True}"
    
    

#///////////////////////////////////////////////  
def _valid_name( str ):
    
    return re.search( "^[A-Za-z0-9 ']{3,64}$", str )

#///////////////////////////////////////////////


def _valid_email( str ):
    return re.search( "^[A-Za-z0-9%._+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,4}$", str )


def main():

   global db
   global am
   global appPath	 
   #----------logging --------------#
   log = logging.getLogger( 'console_log' )        
   log.setLevel (logging.DEBUG)
   ch = logging.StreamHandler(sys.stdout)
	
   log.addHandler(ch)

   try:
      db = CatalogDB(dbconfig)
      db.connect()
      db.check_tables()
   except Exception, e:
      log.error("DB init failure %s" % e)
      exit()
   
   try:    
      am = AuthorizationModule.AuthorizationModule( db, WEB_PROXY )
   except Exception, e:
     log.error( "Authorization Module failure: %s" % ( e, ) )
     exit()
   
   appPath = dirname(__file__)	

   try:
      debug(True)
      run (host="0.0.0.0", port=int(PORT), quiet=False)
   except Exception, e:
      log.error("Web server exception! " % e)
      exit()         

#///////////////constants//////////////////////

configfile = sys.argv[1]
Config = ConfigParser.ConfigParser()
Config.read(configfile)

serverconfig = dict( Config.items( "server" ) )
dbconfig = dict( Config.items( "db" ) )

ROOT_PATH = serverconfig.get("root_path") 
print ROOT_PATH
EXTENSION_COOKIE = serverconfig.get( "extension_cookie" )
PORT = serverconfig.get("port")
ROOT_PAGE = serverconfig.get("root_page")	
WEB_PROXY= serverconfig.get("web_proxy")
REALM = serverconfig.get("realm")
print '%s/views/' % ROOT_PATH
TEMPLATE_PATH.insert(0, '%s/views/' % ROOT_PATH)
    
if not EXTENSION_COOKIE : EXTENSION_COOKIE = "catalog_logged_in"
if not PORT : PORT = 80
if not ROOT_PAGE : ROOT_PAGE = "/"
if not REALM : 
  REALM = "localhost:%s" % PORT
	
#///////////////////////////////////////////////
if __name__ == '__main__':      
	main()
