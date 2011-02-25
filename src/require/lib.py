from zope.interface.advice import addClassAdvisor
import sys

from .error import  Invalid

import copy, logging, inspect
log = logging.getLogger(__name__)


class PASS:
    pass

class __MISSING__( str ):
    def __str__(self):
        return ''

MISSING = __MISSING__()


def _append_list(klass, key, data):
    setattr\
        ( klass
        , "__%s__" % key
        , list(getattr(klass,key,[])) + list(data)
        )

def _merge_dict(klass, key, data):
    fields = dict(getattr\
        ( klass
        , '__%s__' % key
        , {}
        ))

    fields.update( data )

    setattr\
        ( klass
        , "__%s__" % key
        , fields
        )
   
def _merge_fields(klass, key, fields):
    if (len(fields)%2 != 0) or (len(fields)<2):
        raise SyntaxError("Invalid number of fields supplied (%s). Use: %s(key, value, key, value, …)" % (len(fields),key))

    prev_fields = getattr\
        ( klass
        , '__%s__' % key
        , []
        )

    newfields = list(prev_fields)

    field_index = {}
    pos = 0
    for (name, value) in prev_fields:
        field_index[name] = pos
        pos+=1

    pos = 0
    for value in fields:
        if pos%2 != 0:
            if name in field_index:
                newfields[field_index[name]] = (name,value)
            else:
                newfields.append((name,value))
        else:
            name = value
        pos += 1

    setattr\
        ( klass
        , '__%s__' % key
        , newfields
        )

def _callback(klass):
    advice_data = klass.__dict__['__advice_data__']

    for key,(data, callback)  in advice_data.iteritems():
        callback( klass, key, data)

    del klass.__advice_data__

    return klass

def _advice(name, callback,  data, depth=3 ):
    frame = sys._getframe(depth-1)
    locals = frame.f_locals

    if (locals is frame.f_globals) or (
        ('__module__' not in locals) and sys.version_info[:3] > (2, 2, 0)):
        raise SyntaxError("%s can be used only from a class definition." % name)

    if not '__advice_data__' in locals:
        locals['__advice_data__'] = {}

    if name in locals['__advice_data__']:
        raise SyntaxError("%s can be used only once in a class definition." % name)


    if not locals['__advice_data__']:
        addClassAdvisor(_callback, depth=depth)

    locals['__advice_data__'][name] = (data, callback)


def pre_validate(*validators):
    _advice('pre_validate', _append_list,  validators)

def post_validate(*validators):
    _advice('post_validate', _append_list,  validators)

def fieldset(*fields):
    _advice('fieldset', _merge_fields, fields )

def messages(**fields):
    _advice('messages', _merge_dict, fields )

def inherit(*keys):
    _advice('inherit', _append_list, keys)


def defaultErrorFormatter( context, error ):
    return error.msg % (error.extra)



class Context( dict ):
    __value__ = MISSING
    __error__ = MISSING
    __result__ = MISSING

    parent = None
    root = None

    key = ''

    isValidated = False
    isPopulated = False

    def __init__(self, value=MISSING, validator=None, key='', parent=None):
        if parent is not None:
            self.parent = parent
            self.root = parent.root
            self.key = key
            if parent.path:
                self['path'] = '%s.%s' % (parent.path,key)
            else:
                self['path'] = key
        else:
            self.root = self
            self.errorlist = []
            self.errorFormatter = defaultErrorFormatter

        self.validator = validator
        self.value = value

    @property
    def path(self):
        if not 'path' in self:
            return ''
        return self['path']

    @property
    def childs(self):
        if not 'childs' in self:
            self[ 'childs' ] = {}
        return self['childs']

    @property
    def value(self):
        return self.populate()

    @value.setter
    def value( self,value):
        self.__value__ = value
        self.clear()

    @property
    def result(self):
        return self.validate()

    @property
    def error(self):
        if not 'error' in self:
            return MISSING
        return self['error']

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
        if not index in self.indexKeyRelation:
            schemaData = getattr(self,'currentSchemaData',None)
        if schemaData and schemaData.indexFunc:
            self.indexKeyRelation[ index ] = schemaData.indexFunc( index, schemaData )
        else:
            raise SyntaxError('This context has no childs supporting indexing')

        return self.indexKeyRelation[ index ]

    def setSchemaData( self, data ):
        self.indexKeyRelation = {}
        self.currentSchemaData = data
        self.isPopulated = True

    def resetSchemaData( self ):
        del self.currentSchemaData
        self.isPopulated = False

    def clear( self ):
        if not(self.isPopulated or self.isValidated):
            return

        dict.clear( self )

        if parent is not None and parent.path:
            self['path'] = '%s.%s' % (parent.path,self.key)
        else:
            self['path'] = self.key

        self.isValidated = False
        self.isPopulated = False

        self.__result__ = MISSING
        self.__error__ = MISSING

        if self.validator is not None:
            self['value'] = self.__value__

    def populate(self ):
        if self.isPopulated:
            if 'value' in self:
                return self['value']
            return self.__value__

        if self.parent is not None:
            self.parent.populate()

        if self.parent:
            schemaData = getattr(self.parent,'currentSchemaData',None)

        if (self.validator is None) and not schemaData:
            raise AttributeError("No validator set for context '%s'" % self.path )

        result = PASS
        try:
            if schemaData:
                result = schemaData.validationFunc( self, schemaData )
            else:
                result = self.validator.validate( self, self.__value__)
        except Invalid,e:
            self.__error__ = e
        except ValidationDone,e:
            result = e.result

        if not self.__error__:
            if result is not PASS:
                self.__result__ = result
            else:
                self.__result__ = self.__value__

        self.isPopulated = True

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

    def __call__( self, path ):
        if path.__class__ is int:
            if path < 0:
                path = len( self.childs )-path

            return self( self.getKeyByIndex( path ) )

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

    def __init__( self, *args, **kwargs ):
        parent = kwargs.pop( '_parent', None )

        if not hasattr( self, 'setArguments') and args:
            ( args, kwargs ) = self.__realargs__( args, kwargs )

        if parent is not None:
            self.__isRoot__ = False
            newkwargs = dict(parent.__kwargs__ )
            newkwargs.update(kwargs)
            kwargs = newkwargs

            for key in self.__inherit__:
                setattr(self, key, getattr(parent, key))

        for key in self.__getParameterNames__():
            if not key in kwargs and hasattr(self.__class__,key):
                kwargs[key] = getattr(self.__class__, key)

        if args or parent is None:
            if hasattr( self, 'setArguments' ):
                self.setArguments( *args )
            elif args:
                raise SyntaxError('%s takes no further arguments' % self.__class__.__name__)

        if kwargs or parent is None:
            if hasattr( self, 'setParameters' ):
                try:
                    self.setParameters( **kwargs )
                except TypeError, e:
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


    @classmethod
    def __realargs__( klass, args, kwargs ):

        names = klass.__getParameterNames__()

        realargs = list(args)

        for argpos in range(min(len( names ), len(args))):
            if names[ argpos ] in kwargs:
                raise SyntaxError('multiple kw args: %s' % names[ argpos ])
            kwargs[ names[ argpos ] ] = args[argpos]
            del realargs[0]

        return (realargs,kwargs)



