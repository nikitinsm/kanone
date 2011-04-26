from zope.interface.advice import addClassAdvisor
import sys

def _append_list(klass, key, data):
    key = "__%s__" % key
    setattr\
        ( klass
        , key
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

