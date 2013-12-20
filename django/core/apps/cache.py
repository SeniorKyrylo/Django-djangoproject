"Utilities for loading models and the modules that contain them."

from collections import defaultdict, OrderedDict
from contextlib import contextmanager
import os
import sys
import warnings

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_lock
from django.utils._os import upath

from .base import AppConfig


class UnavailableApp(Exception):
    pass


class AppCache(object):
    """
    A cache that stores installed applications and their models. Used to
    provide reverse-relations and for app introspection.
    """

    def __init__(self, master=False):
        # Only one master of the app-cache may exist at a given time, and it
        # shall be the app_cache variable defined at the end of this module.
        if master and hasattr(sys.modules[__name__], 'app_cache'):
            raise RuntimeError("You may create only one master app cache.")

        # When master is set to False, the app cache isn't populated from
        # INSTALLED_APPS and ignores the only_installed arguments to
        # get_model[s].
        self.master = master

        # Mapping of app labels => model names => model classes. Used to
        # register models before the app cache is populated and also for
        # applications that aren't installed.
        self.all_models = defaultdict(OrderedDict)

        # Mapping of labels to AppConfig instances for installed apps.
        self.app_configs = OrderedDict()

        # Set of app names. Allows restricting the set of installed apps.
        # Used by TransactionTestCase.available_apps for performance reasons.
        self.available_apps = None

        # Internal flags used when populating the master cache.
        self._apps_loaded = not self.master
        self._models_loaded = not self.master

        # Pending lookups for lazy relations.
        self._pending_lookups = {}

        # Cache for get_models.
        self._get_models_cache = {}

    def populate_apps(self):
        """
        Populate app-related information.

        This method imports each application module.

        It is thread safe and idempotent, but not reentrant.
        """
        if self._apps_loaded:
            return
        # Since populate_apps() may be a side effect of imports, and since
        # it will itself import modules, an ABBA deadlock between threads
        # would be possible if we didn't take the import lock. See #18251.
        with import_lock():
            if self._apps_loaded:
                return

            # app_config should be pristine, otherwise the code below won't
            # guarantee that the order matches the order in INSTALLED_APPS.
            if self.app_configs:
                raise RuntimeError("populate_apps() isn't reentrant")

            # Application modules aren't expected to import anything, and
            # especially not other application modules, even indirectly.
            # Therefore we simply import them sequentially.
            for app_name in settings.INSTALLED_APPS:
                app_config = AppConfig.create(app_name)
                self.app_configs[app_config.label] = app_config

            self._apps_loaded = True

    def populate_models(self):
        """
        Populate model-related information.

        This method imports each models module.

        It is thread safe, idempotent and reentrant.
        """
        if self._models_loaded:
            return
        # Since populate_models() may be a side effect of imports, and since
        # it will itself import modules, an ABBA deadlock between threads
        # would be possible if we didn't take the import lock. See #18251.
        with import_lock():
            if self._models_loaded:
                return

            self.populate_apps()

            # Models modules are likely to import other models modules, for
            # example to reference related objects. As a consequence:
            # - we deal with import loops by postponing affected modules.
            # - we provide reentrancy by making import_models() idempotent.

            outermost = not hasattr(self, '_postponed')
            if outermost:
                self._postponed = []

            for app_config in self.app_configs.values():

                try:
                    all_models = self.all_models[app_config.label]
                    app_config.import_models(all_models)
                except ImportError:
                    self._postponed.append(app_config)

            if outermost:
                for app_config in self._postponed:
                    all_models = self.all_models[app_config.label]
                    app_config.import_models(all_models)

                del self._postponed

                self._models_loaded = True

    def app_cache_ready(self):
        """
        Returns true if the model cache is fully populated.

        Useful for code that wants to cache the results of get_models() for
        themselves once it is safe to do so.
        """
        return self._models_loaded              # implies self._apps_loaded.

    def get_app_configs(self, only_with_models_module=False):
        """
        Imports applications and returns an iterable of app configs.

        If only_with_models_module in True (non-default), imports models and
        considers only applications containing a models module.
        """
        if only_with_models_module:
            self.populate_models()
        else:
            self.populate_apps()

        for app_config in self.app_configs.values():
            if only_with_models_module and app_config.models_module is None:
                continue
            if self.available_apps is not None and app_config.name not in self.available_apps:
                continue
            yield app_config

    def get_app_config(self, app_label, only_with_models_module=False):
        """
        Imports applications and returns an app config for the given label.

        Raises LookupError if no application exists with this label.

        Raises UnavailableApp when set_available_apps() disables the
        application with this label.

        If only_with_models_module in True (non-default), imports models and
        considers only applications containing a models module.
        """
        if only_with_models_module:
            self.populate_models()
        else:
            self.populate_apps()

        app_config = self.app_configs.get(app_label)
        if app_config is None:
            raise LookupError("No installed app with label %r." % app_label)
        if only_with_models_module and app_config.models_module is None:
            raise LookupError("App with label %r doesn't have a models module." % app_label)
        if self.available_apps is not None and app_config.name not in self.available_apps:
            raise UnavailableApp("App with label %r isn't available." % app_label)
        return app_config

    def get_models(self, app_mod=None,
                   include_auto_created=False, include_deferred=False,
                   only_installed=True, include_swapped=False):
        """
        Given a module containing models, returns a list of the models.
        Otherwise returns a list of all installed models.

        By default, auto-created models (i.e., m2m models without an
        explicit intermediate table) are not included. However, if you
        specify include_auto_created=True, they will be.

        By default, models created to satisfy deferred attribute
        queries are *not* included in the list of models. However, if
        you specify include_deferred, they will be.

        By default, models that aren't part of installed apps will *not*
        be included in the list of models. However, if you specify
        only_installed=False, they will be. If you're using a non-default
        AppCache, this argument does nothing - all models will be included.

        By default, models that have been swapped out will *not* be
        included in the list of models. However, if you specify
        include_swapped, they will be.
        """
        if not self.master:
            only_installed = False
        cache_key = (app_mod, include_auto_created, include_deferred, only_installed, include_swapped)
        model_list = None
        try:
            model_list = self._get_models_cache[cache_key]
            if self.available_apps is not None and only_installed:
                model_list = [
                    m for m in model_list
                    if self.app_configs[m._meta.app_label].name in self.available_apps
                ]
            return model_list
        except KeyError:
            pass
        self.populate_models()
        if app_mod:
            app_label = app_mod.__name__.split('.')[-2]
            if only_installed:
                try:
                    model_dicts = [self.app_configs[app_label].models]
                except KeyError:
                    model_dicts = []
            else:
                model_dicts = [self.all_models[app_label]]
        else:
            if only_installed:
                model_dicts = [app_config.models for app_config in self.app_configs.values()]
            else:
                model_dicts = self.all_models.values()
        model_list = []
        for model_dict in model_dicts:
            model_list.extend(
                model for model in model_dict.values()
                if ((not model._deferred or include_deferred) and
                    (not model._meta.auto_created or include_auto_created) and
                    (not model._meta.swapped or include_swapped))
            )
        self._get_models_cache[cache_key] = model_list
        if self.available_apps is not None and only_installed:
            model_list = [
                m for m in model_list
                if self.app_configs[m._meta.app_label].name in self.available_apps
            ]
        return model_list

    def get_model(self, app_label, model_name, only_installed=True):
        """
        Returns the model matching the given app_label and case-insensitive
        model_name.

        Returns None if no model is found.

        Raises UnavailableApp when set_available_apps() in in effect and
        doesn't include app_label.
        """
        if not self.master:
            only_installed = False
        self.populate_models()
        if only_installed:
            app_config = self.app_configs.get(app_label)
            if app_config is None:
                return None
            if (self.available_apps is not None
                    and app_config.name not in self.available_apps):
                raise UnavailableApp("App with label %s isn't available." % app_label)
        return self.all_models[app_label].get(model_name.lower())

    def register_model(self, app_label, model):
        # Since this method is called when models are imported, it cannot
        # perform imports because of the risk of import loops. It mustn't
        # call get_app_config().
        model_name = model._meta.model_name
        models = self.all_models[app_label]
        if model_name in models:
            # The same model may be imported via different paths (e.g.
            # appname.models and project.appname.models). We use the source
            # filename as a means to detect identity.
            fname1 = os.path.abspath(upath(sys.modules[model.__module__].__file__))
            fname2 = os.path.abspath(upath(sys.modules[models[model_name].__module__].__file__))
            # Since the filename extension could be .py the first time and
            # .pyc or .pyo the second time, ignore the extension when
            # comparing.
            if os.path.splitext(fname1)[0] == os.path.splitext(fname2)[0]:
                return
        models[model_name] = model
        self._get_models_cache.clear()

    def has_app(self, app_name):
        """
        Returns the application config if one is registered and None otherwise.

        It's safe to call this method at import time, even while the app cache
        is being populated. It returns None for apps that aren't loaded yet.
        """
        app_config = self.app_configs.get(app_name.rpartition(".")[2])
        if app_config is not None and app_config.name != app_name:
            app_config = None
        return app_config

    def has_model(self, app_label, model_name):
        """
        Returns the model class if one is registered and None otherwise.

        It's safe to call this method at import time, even while the app cache
        is being populated. It returns None for models that aren't loaded yet.
        """
        return self.all_models[app_label].get(model_name.lower())

    def set_available_apps(self, available):
        """
        Restricts the set of installed apps used by get_app_config[s].

        available must be an iterable of application names.

        Primarily used for performance optimization in TransactionTestCase.
        """
        if self.available_apps is not None:
            raise RuntimeError("set_available_apps() may be called only once "
                "in a row; make sure it's paired with unset_available_apps()")
        available = set(available)
        installed = set(app_config.name for app_config in self.get_app_configs())
        if not available.issubset(installed):
            raise ValueError("Available apps isn't a subset of installed "
                "apps, extra apps: %s" % ", ".join(available - installed))
        self.available_apps = available

    def unset_available_apps(self):
        """
        Cancels a previous call to set_available_apps().
        """
        self.available_apps = None

    ### DANGEROUS METHODS ### (only used to preserve existing tests)

    def _begin_with_app(self, app_name):
        # Returns an opaque value that can be passed to _end_with_app().
        app_config = AppConfig.create(app_name)
        if app_config.label in self.app_configs:
            return None
        else:
            app_config.import_models(self.all_models[app_config.label])
            self.app_configs[app_config.label] = app_config
            if self.available_apps is not None:
                self.available_apps.add(app_config.name)
            return app_config

    def _end_with_app(self, app_config):
        if app_config is not None:
            del self.app_configs[app_config.label]
            if self.available_apps is not None:
                self.available_apps.discard(app_config.name)

    @contextmanager
    def _with_app(self, app_name):
        app_config = self._begin_with_app(app_name)
        try:
            yield
        finally:
            self._end_with_app(app_config)

    def _begin_without_app(self, app_name):
        # Returns an opaque value that can be passed to _end_without_app().
        return self.app_configs.pop(app_name.rpartition(".")[2], None)

    def _end_without_app(self, app_config):
        if app_config is not None:
            self.app_configs[app_config.label] = app_config

    @contextmanager
    def _without_app(self, app_name):
        app_config = self._begin_without_app(app_name)
        try:
            yield
        finally:
            self._end_without_app(app_config)

    def _begin_empty(self):
        app_configs, self.app_configs = self.app_configs, OrderedDict()
        return app_configs

    def _end_empty(self, app_configs):
        self.app_configs = app_configs

    @contextmanager
    def _empty(self):
        app_configs = self._begin_empty()
        try:
            yield
        finally:
            self._end_empty(app_configs)

    ### DEPRECATED METHODS GO BELOW THIS LINE ###

    def load_app(self, app_name):
        """
        Loads the app with the provided fully qualified name, and returns the
        model module.
        """
        warnings.warn(
            "load_app(app_name) is deprecated.",
            PendingDeprecationWarning, stacklevel=2)
        app_config = AppConfig.create(app_name)
        app_config.import_models(self.all_models[app_config.label])
        self.app_configs[app_config.label] = app_config
        return app_config.models_module

    def get_app(self, app_label):
        """
        Returns the module containing the models for the given app_label.

        Raises UnavailableApp when set_available_apps() in in effect and
        doesn't include app_label.
        """
        warnings.warn(
            "get_app_config(app_label).models_module supersedes get_app(app_label).",
            PendingDeprecationWarning, stacklevel=2)
        try:
            return self.get_app_config(
                app_label, only_with_models_module=True).models_module
        except LookupError as exc:
            # Change the exception type for backwards compatibility.
            raise ImproperlyConfigured(*exc.args)

    def get_apps(self):
        """
        Returns a list of all installed modules that contain models.
        """
        warnings.warn(
            "[a.models_module for a in get_app_configs()] supersedes get_apps().",
            PendingDeprecationWarning, stacklevel=2)
        app_configs = self.get_app_configs(only_with_models_module=True)
        return [app_config.models_module for app_config in app_configs]

    def _get_app_package(self, app):
        return '.'.join(app.__name__.split('.')[:-1])

    def get_app_package(self, app_label):
        warnings.warn(
            "get_app_config(label).name supersedes get_app_package(label).",
            PendingDeprecationWarning, stacklevel=2)
        return self._get_app_package(self.get_app(app_label))

    def _get_app_path(self, app):
        if hasattr(app, '__path__'):        # models/__init__.py package
            app_path = app.__path__[0]
        else:                               # models.py module
            app_path = app.__file__
        return os.path.dirname(upath(app_path))

    def get_app_path(self, app_label):
        warnings.warn(
            "get_app_config(label).path supersedes get_app_path(label).",
            PendingDeprecationWarning, stacklevel=2)
        return self._get_app_path(self.get_app(app_label))

    def get_app_paths(self):
        """
        Returns a list of paths to all installed apps.

        Useful for discovering files at conventional locations inside apps
        (static files, templates, etc.)
        """
        warnings.warn(
            "[a.path for a in get_app_configs()] supersedes get_app_paths().",
            PendingDeprecationWarning, stacklevel=2)

        self.populate_models()

        app_paths = []
        for app in self.get_apps():
            app_paths.append(self._get_app_path(app))
        return app_paths

    def register_models(self, app_label, *models):
        """
        Register a set of models as belonging to an app.
        """
        warnings.warn(
            "register_models(app_label, *models) is deprecated.",
            PendingDeprecationWarning, stacklevel=2)
        for model in models:
            self.register_model(app_label, model)


app_cache = AppCache(master=True)
