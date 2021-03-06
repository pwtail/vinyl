import inspect
from copy import copy

from django.db import models
from django.db.models import DEFERRED
from django.db.models.query_utils import DeferredAttribute

from vinyl.futures import gen, later



class ModelMixin:

    def _get_pk_val(self, meta=None):
        meta = meta or self._meta
        return getattr(self, meta.pk.attname)

    def _set_pk_val(self, value):
        for parent_link in self._meta.parents.values():
            if parent_link and parent_link != self._meta.pk:
                setattr(self, parent_link.target_field.attname, value)
        return setattr(self, self._meta.pk.attname, value)

    pk = property(_get_pk_val, _set_pk_val)

    @classmethod
    def from_db(cls, db, field_names, values):
        if len(values) != len(cls._meta.concrete_fields):
            values_iter = iter(values)
            values = [
                next(values_iter) if f.attname in field_names else DEFERRED
                for f in cls._meta.concrete_fields
            ]
        new = cls(*values)
        new._state.adding = False
        new._state.db = db
        return new


class VinylMeta:
    def __get__(self, instance, owner):
        return owner._model._meta


# class ForbidIteration:
#     def __init__(self, *args):
#         self.args = args
#
#     def __iter__(self):
#         raise Exception
#
#
# def forbid_iteration(iterable_class, _iterable_classes={}):
#     if issubclass(iterable_class, ForbidIteration):
#         return iterable_class
#
#     if not (cls := _iterable_classes.get(iterable_class)):
#         cls = type(iterable_class.__name__, (ForbidIteration,), {})
#         _iterable_classes[iterable_class] = cls
#     return cls



#
# def add_mixin(Mixin, obj):
#     bases = (Mixin,) + obj.__class__.__mro__
#     # metacls = type(obj.__class__)
#     name = f'Vinyl{obj.__class__.__name__}'
#     new_cls = type(name, bases, {})
#     new_obj = copy(obj)
#     new_obj.__class__ = new_cls
#     return new_obj
#

class DbHit(Exception):
    pass

def raise_db_hit(*args, **kw):
    raise DbHit

def hits_db(qs):
    iterable_class = qs._iterable_class
    try:
        qs._iterable_class = raise_db_hit
        list(qs)
    except DbHit:
        return True
    else:
        return False
    finally:
        qs._iterable_class = iterable_class


class Proxy:
    # extend_attr = None

    def __init__(self, name, attr):
        self.name = name
        # if self.extend_attr:
        #     attr = self.extend_attr(attr)
        self.attr = attr

    def __get__(self, instance, owner):
        # at = getattr(owner._model, self.name)
        if not instance:
            at = getattr(owner._model, self.name)
            return at
            # return self.attr
        return self.attr.__get__(instance, owner._model)


class FKeyProxy(Proxy):
    # class FKey:
    #     def get_queryset(self, **hints):
    #         qs = super().get_queryset(**hints)
    #         qs._iterable_class = forbid_iteration(qs._iterable_class)
    #         return qs

    def __get__(self, instance, owner):
        if not instance:
            return super().__get__(instance, owner)
        qs = self.attr.get_queryset()
        qs = VinylQuerySet.clone(qs)
        return get_or_none(qs)
        try:
            return qs.get()
        except qs.model.DoesNotExist:
            return None
        # try:
        #     qs._iterable_class = raise_exception()
        #     list(qs)
        # except NotCached:
        #     qs._iterable_class = iterable_class
        #
        #     qs.__class__ = VinylQuerySet
        #     return qs

        if hits_db(qs):
            from vinyl.queryset import VinylQuerySet
            qs = VinylQuerySet.clone(qs)
            return qs.first()
        if qs:
            return qs._result_cache[0]
        # return qs


    # def extend_attr(self, attr):
    #     return add_mixin(self.FKey, attr)

    def __getitem__(self, item):
        return self.instance._prefetched_objects_cache[
            self.field.remote_field.get_cache_name()
        ]



class ManagerProxy(Proxy):
    # class RelatedMgr:
        # def get_queryset(self):
        #     qs = super().get_queryset()
        #     qs._iterable_class = forbid_iteration(qs._iterable_class)
        #     return qs

    def __get__(self, instance, owner):
        if not instance:
            return super().__get__(instance, owner)
        mgr = super().__get__(instance, owner)
        qs = mgr.all()
        from vinyl.queryset import VinylQuerySet
        qs = VinylQuerySet.clone(qs)
        #     return qs
        return qs
        # return add_mixin(self.RelatedMgr, mgr)


class VinylModel(ModelMixin):
    _model = None
    _setup = False

    @classmethod
    def setup(cls):
        """Proxy all fields to django model"""
        if cls._setup:
            return
        for key, val in cls._model.__dict__.items():
            if isinstance(val, DeferredAttribute) or val.__class__.__module__ == 'django.db.models.fields.related_descriptors':
                # print(key, val)
                if val.__class__.__name__.endswith('ToManyDescriptor'):
                    print('ToMany', key)
                    setattr(cls, key, ManagerProxy(key, val))
                elif val.__class__.__name__.endswith('ToOneDescriptor'):
                    print('ToOne', key)
                    setattr(cls, key, FKeyProxy(key, val))
                else:
                    print('other', key)
                    setattr(cls, key, FKeyProxy(key, val))
        cls._setup = True

    _meta = VinylMeta()

    #TODO __init__?
    def __new__(cls, *args, **kwargs):
        ob = cls._model(*args, **kwargs)
        ob._prefetch_cache = {}
        ob.__class__ = cls
        return ob


    # @property
    # def q(self):
    #     from vinyl.lazy import Lazy
    #     return Lazy(self)

    @property
    def insert(self):
        cls = self.__class__
        if cls._meta.parents:
            return self.insert_with_parents
        return self._insert

    def _insert(
        self,
        cls=None,
        using=None,
    ):
        if cls is None:
            cls = self.__class__
        meta = cls._meta

        pk_val = getattr(self, meta.pk.attname)
        if pk_val is None:
            pk_val = meta.pk.get_pk_value_on_save(self)
            setattr(self, meta.pk.attname, pk_val)
        pk_set = pk_val is not None

        fields = meta.local_concrete_fields
        if not pk_set:
            fields = [f for f in fields if f is not meta.auto_field]

        returning_fields = meta.db_returning_fields
        from vinyl.manager import _VinylManager
        manager = _VinylManager()
        manager.model = ensure_vinyl_model(meta.model)
        results = manager._insert(
            [self],
            fields=fields,
            returning_fields=returning_fields,
            using=using,
        )

        @later
        def insert(results=results):
            if results:
                for value, field in zip(results[0], returning_fields):
                    setattr(self, field.attname, value)

        return insert()

    def _insert_with_parents(self, cls=None, using=None):
        if cls is None:
            cls = self.__class__
        meta = cls._meta

        for parent, field in meta.parents.items():
            # Make sure the link fields are synced between parent and self.
            if (
                field
                and getattr(self, parent._meta.pk.attname) is None
                and getattr(self, field.attname) is not None
            ):
                setattr(self, parent._meta.pk.attname, getattr(self, field.attname))
            yield from self._insert_with_parents(cls=parent, using=using)
            if field:
                setattr(self, field.attname, self._get_pk_val(parent._meta))

        yield self._insert(cls=cls, using=using)

    insert_with_parents = gen(_insert_with_parents)

    @property
    def delete(self):
        cls = self.__class__
        if cls._meta.parents:
            return self.delete_with_parents
        return self._delete

    def _delete(self, cls=None, using=None):
        if cls is None:
            cls = self.__class__
        from vinyl.manager import _VinylManager
        manager = _VinylManager()
        manager.model = ensure_vinyl_model(cls._meta.model)
        num_rows = manager._delete(
            [self],
            using=using,
        )
        return num_rows

    def _delete_with_parents(self, cls=None, using=None):
        if cls is None:
            cls = self.__class__
        num_rows = yield self._delete(cls=cls, using=using)

        for parent, field in cls._meta.parents.items():
            count = yield from self._delete_with_parents(cls=parent, using=using)
            num_rows += count

        return num_rows

    delete_with_parents = gen(_delete_with_parents)


    def _update(self, cls=None, using=None, **kwargs):
        cls = self.__class__
        meta = cls._meta

        def values():
            for field in meta.local_concrete_fields:
                if field.primary_key:
                    continue
                if field.name in kwargs:
                    yield field, None, kwargs[field.name]

        values = tuple(values())

        pk_val = self._get_pk_val(meta)
        base_qs = meta.model.vinyl.using(using)
        cursor = base_qs.filter(pk=pk_val)._update(values)

        # TODO returning

        @later
        def update(cursor=cursor):
            count = cursor.rowcount if cursor else 0
            if count == 1:
                for field, _, value in values:
                    setattr(self, field.attname, value)
                return True
            return False

        return update()


vinyl_models = {}


def ensure_vinyl_model(model_cls):
    if issubclass(model_cls, VinylModel):
        return model_cls
    if model := vinyl_models.get(model_cls):
        return model

    model = type(
        model_cls.__name__, (VinylModel,), {'_model': model_cls}
    )
    vinyl_models[model_cls] = model
    return model