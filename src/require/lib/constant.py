class PASS:
    pass

class __MISSING( str ):
    def __str__(self):
        return ''

MISSING = __MISSING()
