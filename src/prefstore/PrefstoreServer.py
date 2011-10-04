"""
Created on 12 April 2011
@author: jog
"""

from __future__ import division
import logging
import logging.handlers
import json
import OpenIDManager
import ProcessingModule
import PrefstoreDB
from bottle import * #@UnusedWildImport
from WebCountUpdater import * #@UnusedWildImport
import MySQLdb
import validictory
import StringIO
import zlib

#setup logger for this module
log = logging.getLogger( "console_log" )
data_log = logging.getLogger( "console_log" )

#//////////////////////////////////////////////////////////
# CONSTANTS
#//////////////////////////////////////////////////////////

TOTAL_WEB_DOCUMENTS = 25000000000

#//////////////////////////////////////////////////////////
# DATAWARE WEB-API CALLS
#//////////////////////////////////////////////////////////
 
@route( '/invoke_request', method = "POST")
def invoke_request():
    
    try:
        access_token = request.forms.get( 'access_token' )
        jsonParams = request.forms.get( 'parameters' )
        result = pm.invoke_request( 
            access_token, 
            jsonParams 
        )
        return result
    
    except Exception, e:
        raise e
     

#///////////////////////////////////////////////
 
 
@route( '/permit_request', method = "POST" )
def permit_request():

    #TODO: Worth checking why this takes so long to parse
    #TODO: the input parameters into the request.forms object.
    #TODO: Long post parameters (queries) are taking ages.   
    try:
        user_id = request.forms.get( 'user_id' )
        catalog_secret = request.forms.get( 'catalog_secret' )
        client_id = request.forms.get( 'client_id' )
        jsonScope = request.forms.get( 'scope' )
        result = pm.permit_request( 
            catalog_secret, 
            client_id,  
            user_id, 
            jsonScope 
        )
        
        #the result, if successful, will include an access_code
        return result
    
    except Exception, e:
        raise e
          

#///////////////////////////////////////////////
 
 
@route( '/revoke_request', method = "POST")
def revoke_request():
    
    try:
        access_token = request.forms.get( 'access_token' )
        catalog_secret = request.forms.get( 'catalog_secret' )
        user_id = request.forms.get( 'user_id' )

        result = pm.revoke_request( 
            user_id,
            catalog_secret,
            access_token, 
        )
        
        return result
    
    except Exception, e:
        raise e


    
#//////////////////////////////////////////////////////////
# OPENID SPECIFIC WEB-API CALLS
#//////////////////////////////////////////////////////////


@route( '/login', method = "GET" )
def openID_login():

    try: 
        username = request.GET[ 'username' ]    
    except: 
        username = None
     
    try:      
        provider = request.GET[ 'provider' ]
    except: 
        return template( 'login_page_template', user=None )
    
    try:
        url = OpenIDManager.process(
            realm=REALM,
            return_to=REALM + "/checkauth",
            provider=provider,
            username=username
        )
    except Exception, e:
        return error( e )
    
    #Here we do a javascript redirect. A 302 redirect won't work
    #if the calling page is within a frame (due to the requirements
    #of some openid providers who forbid frame embedding), and the 
    #template engine does some odd url encoding that causes problems.
    return "<script>self.parent.location = '%s'</script>" % (url,)
    

#///////////////////////////////////////////////

 
@route( "/checkauth", method = "GET" )
def authenticate():
    
    o = OpenIDManager.Response( request.GET )
    
    #check to see if the user logged in succesfully
    if ( o.is_success() ):
        
        user_id = o.get_user_id()
         
        #if so check we received a viable claimed_id
        if user_id:
            
            try:
                user = prefdb.fetch_user_by_id( user_id )
                
                #if this is a new user add them
                if ( not user ):
                    prefdb.insert_user( o.get_user_id() )
                    prefdb.commit()
                    screen_name = None
                else :
                    screen_name = user[ "screen_name" ]
                
                set_authentication_cookie( user_id, screen_name  )
                
            except Exception, e:
                return error( e )
            
            
        #if they don't something has gone horribly wrong, so mop up
        else:
            delete_authentication_cookie()

    #else make sure the user is still logged out
    else:
        delete_authentication_cookie()
        
    redirect( ROOT_PAGE )
       
                
#///////////////////////////////////////////////


@route('/logout')
def logout():
    delete_authentication_cookie()
    redirect( ROOT_PAGE )
    
        
#///////////////////////////////////////////////
 
         
def delete_authentication_cookie():
    response.set_cookie( 
        key=EXTENSION_COOKIE,
        value='',
        max_age=-1,
        expires=0
    )
            
#///////////////////////////////////////////////


def set_authentication_cookie( user_id, screen_name = None ):
    
    #if the user has no "screen_name" it means that they
    #haven't registered an account yet    
    if ( not screen_name ):
        json = '{"user_id":"%s","screen_name":null}' \
            % ( user_id, )
        
    else:
        json = '{"user_id":"%s","screen_name":"%s"}' \
            % ( user_id, screen_name )
         
    response.set_cookie( EXTENSION_COOKIE, json )
                            

#//////////////////////////////////////////////////////////
# PREFSTORE SPECIFIC WEB-API CALLS
#//////////////////////////////////////////////////////////


class LoginException ( Exception ):
    def __init__(self, msg):
        self.msg = msg


#///////////////////////////////////////////////  


class RegisterException ( Exception ):
    """Base class for RegisterException in this module."""
    pass

    
#///////////////////////////////////////////////


def valid_email( str ):
    return re.search( "^[A-Za-z0-9%._+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,4}$", str )


#///////////////////////////////////////////////


def valid_name( str ):
    return re.search( "^[A-Za-z0-9 ']{3,64}$", str )


#///////////////////////////////////////////////


@route( '/register', method = "GET" )
def register():
    
    #TODO: first check the user is logged in!
    try:
        user_id = extract_user_id()
    except LoginException, e:
        return error( e.msg )
    except Exception, e:
        return error( e )
    
    errors = {}
    
    #if the user has submitted registration info, parse it
    try: 
        request.GET[ "submission" ]
        submission = True;
    except:
        submission = False
        
    if ( submission ): 
        #validate the screen name supplied by the user
        try:
            screen_name = request.GET[ "screen_name" ]
            if ( not valid_name( screen_name ) ):
                errors[ 'screen_name' ] = "Must be 3-64 legal characters"    
        except:
            errors[ 'screen_name' ] = "You must supply a valid screen name"
    
        #validate the email address supplied by the user
        try:
            email = request.GET[ "email" ]
            if ( not valid_email( email ) ):
                errors[ 'email' ] = "The supplied email address is invalid"
            else: 
                match = prefdb.fetch_user_by_email( email ) 
                if ( not match is None ):
                    errors[ 'email' ] = "That email has already been taken"
        except:
            errors[ 'email' ] = "You must supply a valid email"


        #if everything is okay so far, add the data to the database    
        if ( len( errors ) == 0 ):
            try:
                match = prefdb.insert_registration( user_id, screen_name, email) 
                prefdb.commit()
            except Exception, e:
                return error( e )

            #update the cookie with the new details
            set_authentication_cookie( user_id, screen_name )
            
            #return the user to the home page
            redirect( ROOT_PAGE )
    
    else:
        email = ""
        screen_name = ""
        
    #if this is the first visit to the page, or there are errors

    return template( 
        'register_page_template', 
        user=None, 
        email=email,
        screen_name=screen_name,
        errors=errors ) 
    

#///////////////////////////////////////////////


@route( '/error', method = "GET" )
def error( e ):
    return "%s: %s" % ( type( e ).__name__, e )

      
#///////////////////////////////////////////////  
    
    
def extract_user_id():
    
    cookie = request.get_cookie( EXTENSION_COOKIE )
        
    #is the user logged in? First check we have a cookie...
    if cookie:
        #and that it contains suitably formatted data
        try:
            data = json.loads( cookie )
        except:
            delete_authentication_cookie()
            raise LoginException( "Your login data is corrupted. Resetting." )
        
        #and then that it contains a valid user_id
        try:
            user_id =  data[ "user_id" ]
            return user_id
        except:
            delete_authentication_cookie()
            raise LoginException( "You are logged in but have no user_id. Resetting." )
    else:
        return None

  
#///////////////////////////////////////////////  
    
    
def check_login():

    #first try and extract the user_id from the cookie. 
    #n.b. this can generate LoginExceptions
    user_id = extract_user_id()
    
    if ( user_id ) :
        
        #we should have a record of this id, from when it was authenticated
        user = prefdb.fetch_user_by_id( user_id )
        
        if ( not user ):
            delete_authentication_cookie()
            raise LoginException( "We have no record of the id supplied. Resetting." )
        
        #and finally lets check to see if the user has registered their details
        if ( user[ "screen_name" ] is None ):
            raise RegisterException()
        
        return user
        
    #if the user has made it this far, their page can be processed accordingly
    else:
        return None   
    
 
    
#//////////////////////////////////////////////////////////
# PREFSTORE SPECIFIC CHROME-API CALLS
#//////////////////////////////////////////////////////////


schema = {
    "type" : "object",
        "properties" : {
            "docId" : {
                "type" : "string",  
                "minLength" : 3 
            },
            "docType" :  {
                "type" : "string",
                "minLength" : 3
            },
            "docName" :  {
                "type" : "string",
                "minLength" : 0
            },
            "appName" : {
                "type" : "string",
                "minLength" : 3
            },
            "totalWords" : {
                "type" : "integer" 
            },
            "duration" : {
                "type" : "integer" 
            },
            "mtime" : {
                "type" : "integer" 
            },
            "fv" : {
                "type" : "object",
                "patternProperties": { ".*": { "type": "integer" } } 
            }      
        }
    }   

       
#///////////////////////////////////////////////


@route( '/submitDistill', method = "POST" )
def submit_distill():
    """ 
        A Distillation is packaged as a json message of the form
        {user:u, docid:d, docType:t, appName:a, duration:d, mtime:m, fv:{ word:freq } }    
    """

    try:
        # First extracted the necessary POST parameters
        user_id = request.forms.get( 'user_id' )
        data = request.forms.get( 'data' ) 
    except:
        log.debug( 
            "%s: Incorrect parameters in submission API call" 
            % ( "prefstore", user_id ) 
        )
        return "{'success':false,'cause':'required parameters missing'}"
        

    try:
        #convert the data into a json object
        data = json.loads( data )

        #Make sure the message is in the correct distill format.
        validictory.validate( data, schema )
               
    except ValueError, e:
        log.error( 
            "%s: Message from '%s': JSON validation error - %s" 
            % ( "prefstore", user_id, e ) 
        )          
        return "{'success':false,'cause':'JSON error'}"       
        
    
    # Log that we have received the distill message.
    log.debug( 
        "%s: Message from '%s' successfully unpacked" 
        % ( "prefstore", user_id ) 
    )
    
       
    try:    
        # First db interaction of this method so safety check in case 
        # a mysql timeout has occurred since we last accessed the db.
        user = prefdb.fetch_user_by_id( user_id ) 
    except Exception, e: 
        log.error( 
            "%s: User Lookup Error %s' due to message from '%s'" 
            % ( "prefstore", e, user_id,  ) 
        )          
        return "{'success':false,'cause':'User Lookup error'}"   
    
    
    # Authenticate the user, using the supplied key
    if user:
        
        log.debug( 
            "%s: Message successfully authenticated as belonging to '%s'" 
            % ( "prefstore", user[ "screen_name" ]  ) 
        )

        # And finally process it into the database
        try:
            process_distill( user, data )
            return "{'success':true}"
        except:
            log.info( 
                "%s: Processing Failure for message from '%s'" 
                % ( "prefstore", user[ "screen_name" ]  )
            ) 
            return "{'success':false,'cause':'Processing error'}"
    
    else:
        log.warning( 
            "%s: Identification Failure for message from '%s'" 
            % ( "prefstore", user[ "screen_name" ]  ) 
        )
        return "{'success':false,'cause':'Authentication error'}"
            
    
#///////////////////////////////////////////////        
       
        
def process_distill( user, data ) :
    
    #Extract entry information
    user_id =  user[ "user_id" ]
    mtime = data.get( 'mtime' )
    fv = data.get( 'fv' )
    start_processing = time.time()
    total_terms = len( fv )
    new_terms = None
    
    #add the distillation to a log file for future analysis
    data_log.info( "%s: %s" % ( request.remote_addr, data ) ) 
    
    #Remove any blacklisted terms from the feature vector
    prefdb.removeBlackListedTerms( fv )
    processed_terms = len( fv )
    total_appearances = sum( fv.values() )
           
    #Process the terms we haven't seen before
    try:
        new_terms = prefdb.insertDictionaryTerms( fv )
    except:
        log.warning( 
            "%s: Error trying to add terms to dictionary"
            % ( "prefstore" ) 
        )
        raise Exception
    
    #Process the terms that already exist in the dictinoary            
    try:
        prefdb.updateTermAppearances( user_id, fv );    
    except:
        log.warning( 
            "%s: Failed to increment term appearances for '%s'" 
            % ( "prefstore", user_id ) 
        )
        raise Exception        

    #Update user info, incrementing the number of documents we have received.
    userUpdated = prefdb.incrementUserInfo( 
        user_id, total_appearances, mtime 
    )

    if not userUpdated :
        log.error( 
            "%s: User '%s' could not be updated. Ignoring." 
            % ( "prefstore", user[ "screen_name" ] ) 
        )
        return False    
      
    #Everything seems okay, so commit the transaction
    prefdb.commit()
    
    #Log the distillation results
    log.info( 
        "%s: Distillation processed for '%s' (%d terms, %d processed, %d new, %d appearances, %.4f secs)" % ( 
            "prefstore", 
            user[ "screen_name" ], 
            total_terms,
            processed_terms, 
            new_terms,
            total_appearances,
            time.time() - start_processing 
        ) 
    )

    #And return from the function successfully
    return True
        

#///////////////////////////////////////////////   


@route('/static/:filename')
def get_static_file( filename ):
    return static_file( filename, root='static/' )


#///////////////////////////////////////////////  

   
@route('/analysis')
def analysis():
    
    try:
        user = check_login()
    except RegisterException, e:
        redirect( "/register" )
    except LoginException, e:
        return error( e.msg )
    except Exception, e:
        return error( e )        
        
    #if the user doesn't exist or is not logged in, send them home
    if ( not user ) :
        redirect( ROOT_PAGE )
    
    try:
        type = request.GET[ "type" ]
    except:
        type = None
        
    try:
        message = "top 1000 terms by total appearances"
        match_type = ""
        search_term = ""
        order_by = ""
        direction = ""
        
        if ( type == "search" ):
            try:
                search_term = request.GET[ "search_term" ]
                match_type = request.GET[ "match_type" ] 
            except:
                pass
            results =  prefdb.search_terms( user[ "user_id" ], search_term, match_type )
            message = "'%s' search for '%s' - %d results" % ( match_type, search_term, len( results ) ) 
        
        elif ( type == "filter" ):
            try:
                direction = request.GET[ "direction" ]
            except:
                direction = "DESC"
                
            try:
                order_by = request.GET[ "order_by" ] 
            except:
                order_by = "total appearances"
                
            results =  prefdb.fetch_terms( user[ "user_id" ], order_by, direction  )
            message = "filtered on '%s' - %s %d results" % ( 
                order_by, 
                "bottom" if direction == "ASC" else "top", 
                len( results )
            ) 
        else:
            results =  prefdb.fetch_terms( user[ "user_id" ] )
            message = "top 1000 results by 'total appearances'" 
        
        data = ""
        
        #TODO: Should also add ability to blacklist terms at some point
        if results:
            for row in results:
                
                #the name of the term
                term = row[ 'term' ]
                
                #the number of times the user has seen this term
                total_appearances = row[ 'total_appearances' ] 
                
                #the number of documents the term has been seen in
                doc_appearances = row[ 'doc_appearances' ]
                
                #the unix timestamp of when the term was last seen
                last_seen = row[ 'last_seen' ]
                
                #the term frequency in the users model (tf)
                frequency = total_appearances / user [ "total_term_appearances" ]

                #the number of web documents the term occurs in (df)
                importance = 0
                
                #the users relevance weight for this term (tf-idf)
                relevance = 0
                
                #at this point there may be no count yet
                if ( row[ 'count' ] > 0 ) :
                    importance = row[ 'count' ] / TOTAL_WEB_DOCUMENTS
                    relevance = ( frequency * ( 1 / importance ) )
                  
                #note below that multiplying by a million serves only to eliminate
                #rounding error that made everything zero.
                data += """
                    {c:[{v:'%s'},{v:%d,f:%s},{v:%d,f:%s},{v:%d,f:'%s'},{v:%d,f:'%s'},{v:%d,f:'%s'},{v:%d,f:'%s'}]},
                """ % ( 
                    term, 
                    total_appearances,str( total_appearances ), 
                    doc_appearances, str( doc_appearances ),
                    frequency * 10000000, '%.5f%%' % round( frequency * 100, 5 ),  
                    importance * 10000000, 'unknown' if ( importance == 0 ) else '%.5f%%' % round( importance * 100, 5 ),
                    relevance * 10000000, 'unknown' if ( relevance == 0 ) else '%.4f' % round( relevance * 100, 4 ),
                    last_seen , time.strftime( "%d %b %Y %H:%M", time.gmtime( last_seen ) )
                )
                
                
        return template(     
            'analysis_page_template',
             data=data,
             user=user,             
             type=type,
             search_term=search_term,
             match_type=match_type,
             order_by=order_by, 
             direction=direction,
             message=message
        )
  
    except Exception, e:
        return error( e )        
  
  
#///////////////////////////////////////////////  
        
    
@route('/visualize')
def word_cloud():
    
    try:
        user = check_login()
    except RegisterException, e:
        redirect( "/register" )
    except LoginException, e:
        return error( e.msg )
    except Exception, e:
        return error( e )        
        
    #if the user doesn't exist or is not logged in,
    #then send them home. naughty user.
    if ( not user ) : redirect( ROOT_PAGE )
    
    try:

        try:
            order_by = request.GET[ "order_by" ] 
        except:
            order_by = "total appearances"
        
        results = prefdb.fetch_terms( 
            user_id=user[ "user_id" ], 
            order_by=order_by, 
            direction="DESC", 
            LIMIT=50, 
            MIN_WEB_PREVALENCE=30000
        )
        
        message = "The %d terms with highest '%s'" % ( 
           len( results ), order_by, 
        ) 
        
        data_str = "{'text':'%s', weight:%d, url:'javascript:select(\"%s\")'},"
        total_appearance_data = ""
        doc_appearance_data = ""
        web_importance_data = ""        
        relevance_data = ""
     
        #TODO: Should also add ability to blacklist terms at some point
        if results:
            for row in results:
                
                #the name of the term
                term = row[ 'term' ]
                
                #the number of times the user has seen this term
                total_appearances = row[ 'total_appearances' ] 
                
                #the number of documents the term has been seen in
                doc_appearances = row[ 'doc_appearances' ]
                
                #the term frequency in the users model (tf)
                frequency = total_appearances / user [ "total_term_appearances" ]

                #the number of web documents the term occurs in (df)
                importance = 0
                
                #the users relevance weight for this term (tf-idf)
                relevance = 0
                
                #at this point there may be no count yet
                if ( row[ 'count' ] > 0 ) :
                    importance = row[ 'count' ] / TOTAL_WEB_DOCUMENTS
                    relevance = ( frequency * ( 1 / importance ) )
                
                total_appearance_data +=  data_str % ( term, total_appearances, term )
                doc_appearance_data +=  data_str % ( term, doc_appearances, term )
                web_importance_data +=  data_str % ( term, importance  * 10000, term )
                relevance_data +=  data_str % ( term, relevance * 10000, term )
               
                #below is some code for image representations of your interests
                #Very neato ;)
                """
                    BING_KEY = "580DDBFFD1A4581F90038B9D5B80BA065FEFE4E7"
                    WEB_PROXY = 'http://mainproxy.nottingham.ac.uk:8080'    
                    search = WebSearch( proxy=WEB_PROXY, bing_key=BING_KEY )
                    urls = []
                    image_count = 0
        
                    if ( image_count < 10 ):
                    urls.append(
                        ( term, search.getBingImage( term ) )
                    )
                    image_count += 1
                    
                    <!-- code for image version of the cloud
                    <img class="term_image" src="{{ urls[ 0 ][ 1 ] }}" title="{{ urls[ 0 ][ 0 ] }}" >
                    <img class="term_image" src="{{ urls[ 1 ][ 1 ] }}" title="{{ urls[ 1 ][ 0 ] }}" >
                    <img class="term_image" src="{{ urls[ 2 ][ 1 ] }}" title="{{ urls[ 2 ][ 0 ] }}" ><br/>
                    <img class="term_image" src="{{ urls[ 3 ][ 1 ] }}" title="{{ urls[ 3 ][ 0 ] }}" >
                    <img class="term_image" src="{{ urls[ 4 ][ 1 ] }}" title="{{ urls[ 4 ][ 0 ] }}" >
                    <img class="term_image" src="{{ urls[ 5 ][ 1 ] }}" title="{{ urls[ 5 ][ 0 ] }}" ><br/>
                    <img class="term_image" src="{{ urls[ 6 ][ 1 ] }}" title="{{ urls[ 6 ][ 0 ] }}" >
                    <img class="term_image" src="{{ urls[ 7 ][ 1 ] }}" title="{{ urls[ 7 ][ 0 ] }}" >
                    <img class="term_image" src="{{ urls[ 8 ][ 1 ] }}" title="{{ urls[ 8 ][ 0 ] }}" >
                    -->
                """ 
       
        data =""" {
            'total appearances':[ %s ],
            'doc appearances':[ %s ],
            'web importance':[ %s ],
            'relevance':[ %s ]
        } """ % (
            total_appearance_data[:-1],
            doc_appearance_data[:-1],
            web_importance_data[:-1],
            relevance_data[:-1],               
        )    
    
        return template(     
            'word_cloud_template',
             user=user,
             data=data,
             order_by=order_by, 
             message=message
        )
  
    except Exception, e:
        return error( e )        
      
  
#///////////////////////////////////////////////  
    
    
@route( '/', method = "GET" )     
@route( '/home', method = "GET" )
def home( ):

    try:
        user = check_login()
    except RegisterException, e:
        redirect( "/register" ) 
    except LoginException, e:
        return error( e.msg )
    except Exception, e:
        return error( e )  
  
    if ( not user ):
        summary = None
    else:
        user[ "registered_str" ] = time.strftime( "%d %b %Y %H:%M", time.gmtime( user[ "registered" ] ) )
        user[ "last_distill_str" ] = time.strftime( "%d %b %Y %H:%M", time.gmtime( user[ "last_distill" ] ) )
        
        if user[ "total_documents" ]:
            user[ "average_appearances" ] = round( user[ "total_term_appearances" ] / user[ "total_documents" ], 2 )
        else:
            user[ "average_appearances" ] = 0
            
        summary = prefdb.fetch_user_summary( user[ "user_id" ] )

    return template( 'home_page_template', user=user, summary=summary );
    
#///////////////////////////////////////////////  
    
    
@route('/summary')
def summary():
  
    try:
        user = check_login()
    except RegisterException, e:
        redirect( "/register" ) 
    except LoginException, e:
        return error( e.msg )
    except Exception, e:
        return error( e )     
    
    #if the user doesn't exist or is not logged in,
    #then send them home. naughty user.
    if ( not user ) : redirect( ROOT_PAGE )

    user[ "registered_str" ] = time.strftime( "%d %b %Y %H:%M", time.gmtime( user[ "registered" ] ) )
    user[ "last_distill_str" ] = time.strftime( "%d %b %Y %H:%M", time.gmtime( user[ "last_distill" ] ) )
    if user[ "total_documents" ]:
        user[ "average_appearances" ] = round( user[ "total_term_appearances" ] / user[ "total_documents" ], 2 )
    else:
        user[ "average_appearances" ] = 0
    summary = prefdb.fetch_user_summary( user[ "user_id" ] )

    return template( 'summary_page_template', user=user, summary=summary );
    
    
#///////////////////////////////////////////////  
    
    
@route('/audit')
def audit():
    
    try:
        user = check_login()
        return template( 'audit_page_template', user=user );
    except RegisterException, e:
        redirect( "/register" ) 
    except LoginException, e:
        return error( e.msg )
    except Exception, e:
        return error( e )  
    
    #if the user doesn't exist or is not logged in,
    #then send them home. naughty user.
    if ( not user ) : redirect( ROOT_PAGE ) 
            
#//////////////////////////////////////////////////////////
# MAIN FUNCTION
#//////////////////////////////////////////////////////////


if __name__ == '__main__' :
    
    #-------------------------------
    # setup logging
    #-------------------------------
    log = logging.getLogger( 'console_log' )
    data_log = logging.getLogger( 'data_log' )
    
    #set logging levels
    log.setLevel( logging.INFO )
    data_log.setLevel( logging.DEBUG )    

    # create handlers
    ch = logging.StreamHandler()
    fh = logging.handlers.TimedRotatingFileHandler( 
        filename='logs/prefstore.log',

        when='midnight', 
        interval=21 )
        
    # create formatter and add it to the handlers
    formatter = logging.Formatter( '--- %(asctime)s [%(levelname)s] %(message)s' )
    ch.setFormatter( formatter )
    fh.setFormatter( formatter )    

    # add the handlers to the logger
    log.addHandler( ch )
    data_log.addHandler( fh )    
    
    #-------------------------------
    # constants
    #-------------------------------
    EXTENSION_COOKIE = "logged_in"
    PORT = 80
    REALM = "http://www.prefstore.org"
    ROOT_PAGE = "/"
        
    #-------------------------------
    # initialization
    #-------------------------------
    try:    
        pm = ProcessingModule.ProcessingModule()
    except Exception, e:
        log.error( "Processing Module failure: %s" % ( e, ) )
        exit()
    
    prefdb = PrefstoreDB.PrefstoreDB()
    prefdb.connect()
    prefdb.check_tables()
    log.info( "database initialisation completed... [SUCCESS]" );
        
    updater = WebCountUpdater()
    updater.start()
    log.info( "web updater initialisation completed... [SUCCESS]" );
                
    try:
        debug( True )
        run( host='0.0.0.0', port=PORT, quiet=True )
    except Exception, e:  
        log.error( "Web Server Startup failed: %s" % ( e, ) )
        exit()
        

   
   
