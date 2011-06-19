""" Twisted adapter for require """

from twisted.python.failure import Failure
from twisted.internet import defer

import logging
log = logging.getLogger( __name__ )

# hacky and redundant, but it'll do for now ..

def monkeyPatch( ):
    """
    Patches require so that any validation returns a Deferred, thus
    one can write asynchrone validators using Twisted's non-blocking API.
    Schema and ForEach fields are validated concurrently.
    """

    from ..lib import Context, PASS, MISSING, Invalid

    from ..validator.core import Tag, Compose, Tmp, Item, Not, And, Or, Call
    from ..validator.check import Match
    from ..validator.schema import Schema, ForEach, Field

    @defer.inlineCallbacks
    def context_validate( self ):
        if self.isValidated:
            if self.__error__ is not MISSING:
                raise self.__error__

            defer.returnValue( self.__result__ )

        self.isValidating = True

        if self.parent is not None:

            if not self.parent.isValidated and not self.parent.isValidating:
                yield defer.maybeDeferred\
                    ( self.parent.validate
                    )
                defer.returnValue( self.result )

        if self.validator is None and not self.isValidating:
            raise AttributeError("No validator set for context '%s'" % self.path )

        result = defer.maybeDeferred\
            ( self.validator.validate
            , self
            , self.__value__
            )

        result.addErrback( context_gotError, self )
        result = yield result

        self.isValidated = True
        self.isValidating = False

        if self.__error__ is not MISSING:
            raise self.__error__

        defer.returnValue( result )

    def context_gotError( error, self ):

        e = error.value 

        if not isinstance( e, Invalid ):
            self.__error__ = error
            return

        self.__error__ = e
        e.context = self
        message = e.validator.__messages__[e.key]

        if message is not None:
            extra = e.data['extra']
            value = e.value
            data = e.data

            data['message'] = message
            if hasattr(e,'realkey'):
                data['key'] = e.realkey

            extra['value.type'] = getattr(value, '__class__', None) is not None \
                and getattr(value.__class__,'__name__', False) or 'unknown'

            if isinstance(value,basestring):
                extra['value'] = value
            else:
                extra['value'] = str(value)

            cache = getattr( self, 'cache', None)
            if cache is not None:
                extra.update( cache )

            self['error'] = self.__error__.data

            self.root.errorlist.append( self.__error__.context.path )
        else:
            if result is not PASS:
                self.__result__ = result
            else:
                self.__result__ = self.__value__

            self.__result__ = result

    def tag_gotResult( result, d, validator, tagName ):
        if isinstance( result, Failure ):
            if not isinstance(result.value, Invalid):
                d.errback( result )
                return

            e = result.value
            if e.validator is validator or getattr(e,'composer',None) is validator:
                e.tagName = tagName
            d.errback( e )
        else:
            d.callback( result )


    def tag_validate( self, context, value ):
        validator = context.root.taggedValidators.get(self.tagID, None)
        if validator is None:
            validator = self.enabled and self.validator

        if validator is False:
            defer.returnValue( value )

        d = defer.Deferred()
        result = defer.maybeDeferred\
                ( validator.validate
                , context
                , value
                )
        result.addBoth( tag_gotResult, d, validator, self.tagName )
        return d

    def compose_gotResult( result, d, tmpTags ):
        context.root.taggedValidators = tmpTags

        if isinstance( result, Failure ):
            if not isinstance( result.value, Invalid ):
                d.errback( result )
                return

            e = result.value

            if hasattr(e,'tagName'):
                e.realkey = "%s_%s" % (e.tagName, getattr(e,'realkey',e.key))
                e.composer = self
                del e.tagName
            d.errback( e )
        else:
            d.callback( result )



    def compose_validate( self, context, value ):
        tmpTags = context.root.taggedValidators
        context.root.taggedValidators = self.currentTaggedValidators

        d = defer.Deferred()
        result = defer.maybeDeferred\
            ( self.validator.validate
            , context
            , value
            )
        result.addBoth( compose_gotResult, d, tmpTags )
        return d


    @defer.inlineCallbacks
    def tmp_validate( self, context, value ):
        try:
            yield defer.maybeDeferred\
                ( self.validator.validate
                , context
                , value
                )
        except Failure as e:
            if not isinstance(e.value, Invalid):
                raise
            e = e.value
            if self.raiseError is True:
                raise

        defer.returnValue( value )

    @defer.inlineCallbacks
    def item_validate( self, context, value ):
        try:
            val = value[ self.key ]

        except TypeError:
            raise Invalid( value, self, 'type' )
        except (KeyError, IndexError):
            raise Invalid( value, self, 'notFound', key=self.key )
        else:
            if self.validator is not None:
                val = yield defer.maybeDeferred\
                    ( self.validator.validate
                    , context
                    , val
                    )
                if self.alter:
                    value[self.key] = val

                defer.returnValue( value )
            else:
                defer.returnValue( val )

    def not_gotResult( result, d, value ):
        if isinstance( result, Failure ):
            if not isinstance( result.value, Invalid ):
                d.errback( result )
                return
            d.callback( value )
        else:
            d.errback( Invalid( value, self ) )

    def not_validate(self, context, value ):
        d = defer.Deferred()
        result = defer.maybeDeferred\
            ( self.validator.validate
            , context
            , value
            )
        d.addCallback( not_gotResult, d, value )
        return d

    def and_doTryNext( result, validators, context, value, d ):
        if isinstance( result, Failure ):
            if not isinstance(result.value, Invalid):
                d.errback( result )

            e = result.value
            d.errback( e )
        else:
            if validators:
                or_tryNext( validators, context, result, d )
            else:
                d.callback( result )

    def and_tryNext( validators, context, value, d ):
        result = defer.maybeDeferred\
            ( validators.pop(0).validate
            , context
            , value
            )

        result.addBoth( and_doTryNext, validators, context, value, d )

    def and_validate( self, context, value ):
        d = defer.Deferred()
        and_tryNext( list( self.validators ), context, value, d )
        return d

    def or_doTryNext( result, validators, context, value, d ):
        if isinstance( result, Failure ):
            err = result
        
            if not isinstance(err.value, Invalid):
                d.errback( err )

            e = err.value
            if not validators:
                d.errback( e )
            else:
                or_tryNext( validators, context, value, d )
        else:
            d.callback( result )

    def or_tryNext( validators, context, value, d ):
        result = defer.maybeDeferred\
            ( validators.pop(0).validate
            , context
            , value
            )

        result.addBoth( or_doTryNext, validators, context, value, d )

    def or_validate( self, context, value ):
        d = defer.Deferred()
        or_tryNext( list(self.validators), context, value, d )
        return d



    @defer.inlineCallbacks
    def call_validate( self, context, value ):
        try:
            result = yield defer.maybeDeferred\
                ( self.__func__
                , context
                , value
                )
        except Failure as e:
            if not isinstance(e.value, Invalid):
                raise
            e = e.value
            e.validator = self
            raise e
        else:
            defer.returnValue( result )

    def match_gotResult( result, self, value, d ):
        if isinstance( result, Failure ):
            if not isinstance(e.value, Invalid):
                raise
            e = e.value
            d.errback( Invalid( value, self, matchType=self.type, criteria=e ) )
        else:
            if self.ignoreCase:
                compare = str(compare).lower()
                val = str(value).lower()

            if val != compare:
                d.errback( Invalid( value, self, matchType=self.type, criteria=compare ) )
            else:
                d.callback( value )
           

    def match_on_value(self, context, value ):
        if self.type is Match.REGEX:
            if not self.required.match(value):
                raise Invalid( value, self, matchType=self.type, criteria=self.required.pattern)
            return value
        elif self.type is Match.RAW:
            compare = self.required
        elif self.type is Match.VALIDATOR:
            compare = defer.maybeDeferred\
                ( self.required.validate
                , context
                , value
                )

            d = defer.Deferred()
            compare.addBoth( match_gotResult, self, value, d )
            return d

        val = value
        if self.ignoreCase:
            compare = str(compare).lower()
            val = str(value).lower()

        if val != compare:
            raise Invalid( value, self, matchType=self.type, criteria=compare )

        return value

    def schema_gotResult( result, resultset, key, isList ):
        if self.returnList:
            resultset.append( result )
        else:
            resultset[ key ] = result

        return result

    def schema_gotError( error, errorset, key ):
        errors.append( error.context.key )


    @defer.inlineCallbacks
    def schema__on_value( self, context, value ):
        isList = isinstance(value, list) or isinstance(value,tuple) or isinstance(value,set)
        if not isList and not isinstance( value, dict ):
            raise Invalid( value, self, 'type')

        extraFields = None
        if not self.allowExtraFields:
            if isList:
                extraFields = max( len(value), len(self.index) )
            else:
                extraFields = value.keys()

        if self.returnList:
            result = []
        else:
            result = {}

        numValues = len(value)
        jobs = []

        for pos in xrange(len(self.index)):
            key = self.index[pos]
            if isList is True:
                if numValues>pos:
                    val = value[ pos ]
                    if not self.allowExtraFields:
                        extraFields-=1
                else:
                    val = MISSING
            else:
                val = value.get( key, MISSING)
                if not self.allowExtraFields and val is not MISSING:
                    try: extraFields.remove(key)
                    except: pass

            job = defer.maybeDeferred\
                ( self.validators[ key ].validate
                , context
                , val
                )

            jobs.append( job.addCallback( schema_gotResult, result, key, isList ) )

        yield defer.DeferredList( jobs )

        if extraFields:
            raise Invalid( value, self, 'extraFields',extraFields=extraFields)

        defer.returnValue( result )

    @defer.inlineCallbacks
    def schema__createContextChilds_on_value( self, context, value ):
        isList = isinstance(value, list) or isinstance(value,tuple) or isinstance(value,set)

        if not isList and not isinstance( value, dict ):
            raise Invalid( value, self, 'type')

        extraFields = None
        if not self.allowExtraFields:
            if isList:
                extraFields = max( len(value), len(self.index) )
            else:
                extraFields = value.keys()

        errors = []

        if self.returnList:
            result = []
        else:
            result = {}

        len_value = len(value)
        len_index = len(self.index)

        # populate
        for pos in xrange(len_index):
            key = self.index[pos]
            childContext = context( key )
            try:
                childContext.validator = self.validators[ key ]
            except KeyError:
                raise SyntaxError("No validator set for %s" % childContext.path)

            if isList:
                if len_value<=pos:
                    childContext.__value__ = MISSING
                else:
                    childContext.__value__ = value[ pos ]
            else:
                childContext.__value__ = value.get( key, MISSING )

            if not self.allowExtraFields:
                if isList:
                    extraFields-=1
                else:
                    try: extraFields.remove(key)
                    except: pass

        if extraFields:
            raise Invalid( value, self, 'extraFields',extraFields=extraFields)

        context.setIndexFunc( lambda index: self.index[index] )

        jobs = []

        # validate
        for key in self.index:

            jobs.append\
                ( defer.maybeDeferred( context( key ).result )\
                    .addCallback( schema_gotResult, result, key, isList )\
                    .addErrback( schema_gotError, errors, key )
                )

        yield defer.DeferredList( jobs )

        if errors:
            raise Invalid( value, self, errors=errors )

        defer.returnValue( result )

    @defer.inlineCallbacks
    def forEach__on_value( self, context, value ):
        if self.returnList:
            result = []
        else:
            result = {}

        isList = isinstance( value, list) or isinstance(value, tuple) or isinstance(value, set)

        jobs = []
        if isList or self.numericKeys:
            for pos in xrange( len( value ) ):
                if isList is False:
                    val = value.get(str(pos),MISSING)
                    if val is MISSING:
                        raise Invalid( value, self, 'numericKeys', keys=value.keys() )
                else:
                    val = value[pos]

                jobs.append\
                    ( defer.maybeDeferred\
                        ( self.validator.validate
                        , context, val
                        ).addCallback( schema_gotResult, result, str(pos), isList )
                    )
        else:
            for (key, val) in value.iteritems():

                jobs.append\
                    ( defer.maybeDeferred\
                        ( self.validator.validate
                        , context, val
                        ).addCallback( schema_gotResult, result, key, isList )
                    )

        yield defer.DeferredList( jobs )
        defer.returnValue( result )


    @defer.inlineCallbacks
    def forEach__createContextChilds_on_value( self, context, value ):
        isList = isinstance( value, list) or isinstance(value, tuple) or isinstance(value, set)

        if not isList:
            if not isinstance(value, dict ):
                raise Invalid( value, self,'type' )

        if self.returnList:
            result = []
        else:
            result = {}
        errors = []

        # populate
        childs = []
        if isList or self.numericKeys:
            context.setIndexFunc( lambda index: str(index) )

            for pos in xrange( len( value ) ):
                if not isList:
                    val = value.get(str(pos),MISSING)
                    if value.get(str(pos),MISSING) is MISSING:
                        context.setIndexFunc( None )
                        raise Invalid( value, self, 'numericKeys',keys=value.keys())

                else:
                    val = value[ pos ]

                contextChild = context( str( pos ) )
                contextChild.validator = self.validator
                contextChild.__value__ = val
                childs.append( contextChild )

        else:
            context.setIndexFunc( None )

            if self.returnList:
                raise Invalid( value, self, 'listType' )
            for (key,val) in value.iteritems():
                contextChild = context( key )
                contextChild.validator = self.validator
                contextChild.__value__ = val
                childs.append( contextChild )

        jobs = []
        #validate
        for childContext in childs:
            jobs.append\
                ( defer.maybeDeferred( childContext.result )\
                    .addCallback\
                        ( result
                        , childContext.key
                        , isList
                        )\
                    .addErrback\
                        ( errors
                        , childContext.key
                        )
                )

        yield defer.DeferredList( jobs )

        if errors:
            raise Invalid( value, self, errors=errors )

        defer.returnValue( result )


    @defer.inlineCallbacks
    def field_validate(self, context, value):
        fieldcontext = self.getField( context, self.path )

        result = PASS

        if not self.useResult:
            result = fieldcontext.value

        else:
            try:
                result = fieldcontext.result
            except Failure as e:
                if not isinstance(e.value, Invalid):
                    raise
                result = PASS

        if self.validator is not None:
            if result is not PASS:
                result = yield defer.maybeDeferred\
                    ( self.validator.validate
                    , fieldcontext, result
                    )

        if self.writeToContext is True:
            fieldcontext.__result__ = result

        if self.copy:
            if result is PASS:
                defer.returnValue( value )

            defer.returnValue( result )

        defer.returnValue( value )


    Context.validate = context_validate
    Tag.validate = tag_validate
    Compose.valdate = compose_validate
    Tmp.validate = tmp_validate
    Item.validate = item_validate
    Not.validate = not_validate
    And.validate = and_validate
    Or.validate = or_validate
    Call.validate = call_validate
    Match.on_value = match_on_value
    Schema._on_value = schema__on_value
    Schema._createContextChilds_on_value = schema__createContextChilds_on_value
    ForEach._on_value = forEach__on_value
    ForEach._createContextChilds_on_value = forEach__createContextChilds_on_value
    Field.validate = field_validate

