# -*- coding: utf-8 -*-

from .constant import MISSING,PASS

import logging, inspect
log = logging.getLogger(__name__)


class Invalid(BaseException):
    context = None

    def __init__(self, value, _validator=None, _key='fail', **kwargs):
        if _validator is not None:
            self.validator = _validator
        self.value = value
        self.data = {'key': _key, 'extra': kwargs}

    @property
    def key(self):
        return self.data['key']

    @key.setter
    def key(self, value):
        self.data['key'] = value

    @property
    def message(self):
        return self.data.get('message',None)

    @property
    def extra(self):
        return self.data['extra']

    def __repr__(self):
        return 'Invalid(%s, %s)' % (self.value, self.key)

    def __str__(self):
        if self.context is not None and self.message is not None:
            return self.context.root.errorFormatter( self.context, self )
        else:
            return self.__repr__()


def defaultErrorFormatter( context, error ):
    return error.message % (error.extra)

class Context( dict ):

    __value__ = MISSING
    __error__ = MISSING
    __result__ = MISSING

    parent = None
    root = None
    key = '/'

    isValidated = False
    isValidating = False

    taggedValidators = {}
    indexKeyRelation = {}
    numValues = 0

    def __init__(self, validator=None, value=MISSING, key='/', parent=None):
        if parent is not None:
            self.parent = parent
            self.root = parent.root
            self.key = key

            sep = self.root is not parent and '.' or ''

            self['path'] = '%s%s%s' % (parent.path,sep,key)
        else:
            self.root = self
            self.errorFormatter = defaultErrorFormatter
            self['path'] = key

        self.validator = validator
        self.value = value

    @property
    def path(self):
        return self['path']

    @property
    def childs(self):
        childs = self.get('childs',None)
        if childs is None:
            childs = self[ 'childs' ] = {}
        return childs

    @property
    def errorlist(self):
        errorlist = self.get('errorlist',None)
        if errorlist is None:
            errorlist = self[ 'errorlist' ] = []
        return errorlist

    @property
    def updates(self):
        updates = self.get('updates',None)
        if updates is None:
            updates = self[ 'updates' ] = []
        return updates

    @property
    def value(self):
        return self.get('value',self.__value__)

    @value.setter
    def value( self, value):
        if value is self.value:
            return

        if self.root.isValidating:
            self['value'] = value
            self.root.updates.append( self.path )
            return

        if (value == '') or value is [] or value is {}:
            value = None

        self.__value__ = value
        self.clear()

    @property
    def result(self):
        return self.validate()

    @property
    def error(self):
        return str(self.__error__)

    @property
    def validator(self):
        if not hasattr(self, '__validator__'):
            return None
        return self.__validator__

    @validator.setter
    def validator(self,value):
        self.__validator__ = value
        self.clear()

    def getKeyByIndex( self, index ):
        key = self.indexKeyRelation.get( index, None )
        if key is not None:
            return key

        schemaData = getattr(self,'currentSchemaData',None)

        if schemaData and schemaData.indexFunc:
            if not self.indexKeyRelation:
                self.numValues = len(schemaData.values)
            self.indexKeyRelation[ index ] = schemaData.indexFunc( index, schemaData )
            return self.indexKeyRelation[ index ]
        else:
            raise SyntaxError('Context %s has no childs supporting indexing' % (self.path))

    def setSchemaData( self, data ):
        self.__result__ = MISSING
        self.__error__ = MISSING
        self.indexKeyRelation = {}
        self.currentSchemaData = data

    def resetSchemaData( self ):
        del self.currentSchemaData

    def clear( self, force=False ):
        if not self.isValidated and not force:
            return

        dict.clear( self )

        if self.parent is not None and self.parent.path:
            self['path'] = '%s.%s' % (self.parent.path,self.key)
        else:
            self['path'] = self.key

        self.isValidated = False

        self.__result__ = MISSING
        self.__error__ = MISSING

    def validate(self ):
        if self.isValidated:
            if self.__error__ is not MISSING:
                raise self.__error__
            return self.__result__

        self.isValidating = True

        schemaData = None
        if self.parent is not None:

            if not self.parent.isValidated and not self.parent.isValidating:
                res = self.parent.validate()
                return self.result

            schemaData = getattr(self.parent,'currentSchemaData',None)

        if (self.validator is None and not self.isValidating ) and schemaData is None:
            raise AttributeError("No validator set for context '%s'" % self.path )

        result = PASS
        try:
            if schemaData:
                result = schemaData.validationFunc( self, schemaData )
            else:
                result = self.validator.validate( self, self.__value__)

        except Invalid as e:
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

            raise e
        else:
            if result is not PASS:
                self.__result__ = result
            else:
                self.__result__ = self.__value__

            return self.__result__
        finally:
            self.isValidated = True
            self.isValidating = False



    """
    def populate(self ):
        if self.isPopulated:
            if 'value' in self:
                return self['value']
            return self.__value__

        if self.parent is not None:
            self.parent.populate()

        schemaData = None
        if self.parent:
            schemaData = getattr(self.parent,'currentSchemaData',None)

        if self.validator is None:
            raise AttributeError("No validator set for context '%s'" % self.path )

        result = PASS
        try:
            if schemaData:
                result = schemaData.validationFunc( self, schemaData )
            else:
                result = self.validator.validate( self, self.__value__)
        except Invalid as e:
            self.__error__ = e

        if not self.__error__:
            if result is not PASS:
                self.__result__ = result
            else:
                self.__result__ = self.__value__

        self.isPopulated = True
        if not 'value' in self:
            self['value'] = self.__value__

        return self['value']

    def validate(self ):

        if not self.isPopulated:
            self.populate()

        if not self.isValidated:

            if self.__result__ is not MISSING:
                self['result'] = self.__result__
            elif self.__error__ is not MISSING:
                self.errorlist.append( self.path )
                self['error'] = self.__error__

            self.isValidated = True

        if self.__error__ is MISSING:
            return self.__result__

        raise self.__error__
    """

    def __call__( self, path ):
        if path.__class__ is int:
            if path < 0:
                path = self.numValues+path

            return self( self.getKeyByIndex( path ) )
        elif not path:
            raise SyntaxError('Path cannot be empty')

        path = path.split('.',1)

        try:
            child = self.childs[path[0]]
        except KeyError:
            child = self.childs[path[0]] = Context( key=path[0], parent=self )

        if(len(path)==1):
            return child
        else:
            path=path[1]

        return child(path)


from ..util import varargs2kwargs
# Some kind of 'clonable' object -
# we reinitialize child objects with inherited kwargs merged with new ones.
# This allows us to alter just a few specific parameters in child objects.
# without the need for implementors of validators to provide setters or too
# much specification for their attributes or how they are provided.
# * the setParameters function will be inspected, so that it will use
#   named parameters as kwargs, regardless if they are provided as *args
#   ( you cannot use *varargs in setParameters )
# * you can also define a setArguments function, which will be called before
#   setParameters, using the provided *varargs. keywords defined in
#   setParameters will not be moved from *args to **kwargs when setArguments
#   is defined. You can use it for attributes you only want to initialize
#   once. It also allows you to 'name' *varargs in the function definition.
# * __inherit__ specifies what attributes should be copied to child instances.
class Parameterized:
    __kwargs__ = {}
    __inherit__ = [ ]
    __isRoot__ = True

    __ignoreClassParameters__ = []

    def __init__( self, *args, **kwargs ):
        parent = kwargs.pop( '_parent', None )

        if not hasattr( self, 'setArguments') and args:
            func = getattr( self, 'setParameters', None)
            if func is not None:
                ( args, kwargs, shifted ) = varargs2kwargs( func, args, kwargs )

        if parent is not None:
            self.__isRoot__ = False
            newkwargs = dict(parent.__kwargs__ )
            newkwargs.update(kwargs)
            kwargs = newkwargs

            for key in self.__inherit__:
                setattr(self, key, getattr(parent, key))
        else:
            for key in self.__getParameterNames__():
                if hasattr(self.__class__,key)\
                and not key in self.__ignoreClassParameters__\
                and not key in kwargs:
                    kwargs[key] = getattr(self.__class__, key)

        if args or (parent is None):
            if hasattr( self, 'setArguments' ):
                self.setArguments( *args )
            elif args:
                raise SyntaxError('%s takes no further arguments' % self.__class__.__name__)

        if hasattr( self, 'setParameters' ):
            try:
                self.setParameters( **kwargs )
            except TypeError as e:
                raise TypeError(self.__class__.__name__+': '+e[0])

        elif kwargs:
            raise SyntaxError('%s takes no parameters' % self.__class__.__name__)

        self.__kwargs__ = kwargs

    def __call__( self, *args, **kwargs):
        kwargs['_parent'] = self
        return self.__class__( *args, **kwargs )


    @classmethod
    def __getParameterNames__( klass ):
        if not hasattr( klass, '__parameterNames__'):
            if not hasattr( klass, 'setParameters'):
                names = ()
            else:
                spec = inspect.getargspec( klass.setParameters )
                if spec.varargs:
                    raise SyntaxError('Cannot use *varargs in setParameters, please use %s.setArguments' % klass.__name__)
                names = spec.args[1:]
            setattr\
                ( klass,'__parameterNames__'
                , names
                )
        return klass.__parameterNames__
