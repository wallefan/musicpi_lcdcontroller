class BaseAnnotation:
    def __init__(self):
        self.value = None

    def __call__(self, obj):
        self.value = obj
        return self


class AnnoNamespace(dict):
    __slots__ = ('_annotations',)

    def __init__(self):
        super().__init__()
        super().__setitem__('_annotations', {})

    def __setitem__(self, key, value):
        if isinstance(value, BaseAnnotation):
            super().__setitem__(key, value.value)
            self['_annotations'][key] = value
        else:
            super().__setitem__(key, value)


class AnnoMeta(type):
    @staticmethod
    def __prepare__(name, bases):
        return AnnoNamespace()



