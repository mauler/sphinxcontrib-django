"""Improve the Django model docstrings.

For example:
* Automatically mention all model fields as parameters in the model construction.
* Mention form fields.
* Improve field representations in the documentation.

Based on:

* https://gist.github.com/abulka/48b54ea4cbc7eb014308
* https://gist.github.com/codingjoe/314bda5a07ff3b41f247
"""
import re

from django import forms, get_version
from django.db import models
from django.db.models.fields.files import FileDescriptor
from django.db.models.query_utils import DeferredAttribute
from django.db.models.fields import related_descriptors
from django.db.models.manager import ManagerDescriptor
from django.utils.encoding import force_text
from django.utils.html import strip_tags
from django.utils.module_loading import import_string

from sphinxcontrib_django import config

_FIELD_DESCRIPTORS = (FileDescriptor,)
RE_GET_FOO_DISPLAY = re.compile('\.get_(?P<field>[a-zA-Z0-9_]+)_display$')
RE_GET_NEXT_BY = re.compile('\.get_next_by_(?P<field>[a-zA-Z0-9_]+)$')
RE_GET_PREVIOUS_BY = re.compile('\.get_previous_by_(?P<field>[a-zA-Z0-9_]+)$')


IS_DJANGO2 = get_version()[0] == '2'


def get_field_type(field):
    # Add type
    if isinstance(field, models.ForeignKey):
        if IS_DJANGO2:
            to = field.remote_field
            to_name = to.name
        else:
            to = field.rel.to
            to_name = to.__name__
        return u':type %s: %s to :class:`~%s.%s`' % (field.name,
                                                     type(field).__name__,
                                                     to.__module__,
                                                     to_name)
    else:
        return u':type %s: %s' % (field.name, type(field).__name__)


# Support for some common third party fields
try:
    from phonenumber_field.modelfields import PhoneNumberDescriptor
    _FIELD_DESCRIPTORS += (PhoneNumberDescriptor,)
except ImportError:
    PhoneNumberDescriptor = None


def setup(app):
    """Allow this package to be used as Sphinx extension.
    This is also called from the top-level ``__init__.py``.

    :type app: sphinx.application.Sphinx
    """
    from .patches import patch_django_for_autodoc

    # When running, make sure Django doesn't execute querysets
    patch_django_for_autodoc()

    # Generate docstrings for Django model fields
    # Register the docstring processor with sphinx
    app.connect('autodoc-process-docstring', improve_model_docstring)

    # influence skip rules
    app.connect("autodoc-skip-member", autodoc_skip)


def autodoc_skip(app, what, name, obj, skip, options):
    """Hook that tells autodoc to include or exclude certain fields.

    Sadly, it doesn't give a reference to the parent object,
    so only the ``name`` can be used for referencing.

    :type app: sphinx.application.Sphinx
    :param what: The parent type, ``class`` or ``module``
    :type what: str
    :param name: The name of the child method/attribute.
    :type name: str
    :param obj: The child value (e.g. a method, dict, or module reference)
    :param options: The current autodoc settings.
    :type options: dict

    .. seealso:: http://www.sphinx-doc.org/en/stable/ext/autodoc.html#event-autodoc-skip-member
    """
    if name in config.EXCLUDE_MEMBERS:
        return True

    if name in config.INCLUDE_MEMBERS:
        return False

    return skip


def improve_model_docstring(app, what, name, obj, options, lines):
    """Hook that improves the autodoc docstrings for Django models.

    :type app: sphinx.application.Sphinx
    :param what: The parent type, ``class`` or ``module``
    :type what: str
    :param name: The dotted path to the child method/attribute.
    :type name: str
    :param obj: The Python object that i s being documented.
    :param options: The current autodoc settings.
    :type options: dict
    :param lines: The current documentation lines
    :type lines: list
    """
    if what == 'class':
        _improve_class_docs(app, obj, lines)
    elif what == 'attribute':
        _improve_attribute_docs(obj, name, lines)
    elif what == 'method':
        _improve_method_docs(obj, name, lines)

    # Return the extended docstring
    return lines


def _improve_class_docs(app, cls, lines):
    """Improve the documentation of a class."""
    if issubclass(cls, models.Model):
        _add_model_fields_as_params(app, cls, lines)
    elif issubclass(cls, forms.Form):
        _add_form_fields(cls, lines)


def _add_model_fields_as_params(app, obj, lines):
    """Improve the documentation of a Django model subclass.

    This adds all model fields as parameters to the ``__init__()`` method.

    :type app: sphinx.application.Sphinx
    :type lines: list
    """
    for field in obj._meta.get_fields():
        try:
            help_text = strip_tags(force_text(field.help_text))
            verbose_name = force_text(field.verbose_name).capitalize()
        except AttributeError:
            # e.g. ManyToOneRel
            continue

        # Add parameter
        if help_text:
            lines.append(u':param %s: %s' % (field.name, help_text))
        else:
            lines.append(u':param %s: %s' % (field.name, verbose_name))

        lines.append(get_field_type(field))

    if 'sphinx.ext.inheritance_diagram' in app.extensions and \
            'sphinx.ext.graphviz' in app.extensions and \
            not any('inheritance-diagram::' in line for line in lines):
        lines.append('.. inheritance-diagram::')


def _add_form_fields(obj, lines):
    """Improve the documentation of a Django Form class.

    This highlights the available fields in the form.
    """
    lines.append("**Form fields:**")
    lines.append("")
    for name, field in obj.declared_fields.items():
        field_type = "{}.{}".format(field.__class__.__module__, field.__class__.__name__)
        tpl = "* ``{name}``: {field.label} (:class:`~{field_type}`)"
        lines.append(tpl.format(name=name, field=field, field_type=field_typr))


def _improve_attribute_docs(obj, name, lines):
    """Improve the documentation of various attributes.
    This improves the navigation between related objects.

    :param obj: the instance of the object to document.
    :param name: full dotted path to the object.
    :param lines: expected documentation lines.
    """
    if obj is None:
        # Happens with form attributes.
        return

    if isinstance(obj, DeferredAttribute):
        # This only points to a field name, not a field.
        # Get the field by importing the name.
        cls_path, field_name = name.rsplit('.', 1)
        model = import_string(cls_path)
        field = model._meta.get_field(obj.field_name)

        lines.clear()
        lines.append("**Model field:** {label}".format(
            label=field.verbose_name
        ))
    elif isinstance(obj, _FIELD_DESCRIPTORS):
        # These
        lines.clear()
        lines.append("**Model field:** {label}".format(
            label=obj.field.verbose_name
        ))

        if isinstance(obj, FileDescriptor):
            lines.append("**Return type:** :class:`~django.db.models.fields.files.FieldFile`")
        elif PhoneNumberDescriptor is not None and isinstance(obj, PhoneNumberDescriptor):
            lines.append("**Return type:** :class:`~phonenumber_field.phonenumber.PhoneNumber`")
    elif isinstance(obj, related_descriptors.ForwardManyToOneDescriptor):
        # Display a reasonable output for forward descriptors.
        related_model = obj.field.remote_field.model
        cls_path = "{}.{}".format(related_model.__module__, related_model.__name__)
        lines.clear()
        lines.append("**Model field:** {label}, "
                     "accesses the :class:`~{cls_path}` model.".format(
            label=obj.field.verbose_name, cls_path=cls_path
        ))
    elif isinstance(obj, related_descriptors.ReverseOneToOneDescriptor):
        related_model = obj.related.related_model
        cls_path = "{}.{}".format(related_model.__module__, related_model.__name__)
        lines.clear()
        lines.append("**Model field:** {label}, "
                     "accesses the :class:`~{cls_path}` model.".format(
            label=obj.related.field.verbose_name, cls_path=cls_path
        ))
    elif isinstance(obj, related_descriptors.ReverseManyToOneDescriptor):
        related_model = obj.rel.related_model
        cls_path = "{}.{}".format(related_model.__module__, related_model.__name__)
        lines.clear()
        lines.append("**Model field:** {label}, "
                     "accesses the M2M :class:`~{cls_path}` model.".format(
            label=obj.field.verbose_name, cls_path=cls_path
        ))
    elif isinstance(obj, (models.Manager, ManagerDescriptor)):
        # Somehow the 'objects' manager doesn't pass through the docstrings.
        module, cls_name, field_name = name.rsplit('.', 2)
        lines.append("Django manager to access the ORM")
        tpl = "Use ``{cls_name}.objects.all()`` to fetch all objects."
        lines.append(tpl.format(cls_name=cls_name))


def _improve_method_docs(obj, name, lines):
    """Improve the documentation of various methods.

    :param obj: the instance of the method to document.
    :param name: full dotted path to the object.
    :param lines: expected documentation lines.
    """
    if not lines:
        # Not doing obj.__module__ lookups to avoid performance issues.
        if name.endswith('_display'):
            match = RE_GET_FOO_DISPLAY.search(name)
            if match is not None:
                # Django get_..._display method
                lines.append("**Autogenerated:** Shows the label of the :attr:`{field}`".format(
                    field=match.group('field')
                ))
        elif '.get_next_by_' in name:
            match = RE_GET_NEXT_BY.search(name)
            if match is not None:
                lines.append("**Autogenerated:** Finds next instance"
                             " based on :attr:`{field}`.".format(
                    field=match.group('field')
                ))
        elif '.get_previous_by_' in name:
            match = RE_GET_PREVIOUS_BY.search(name)
            if match is not None:
                lines.append("**Autogenerated:** Finds previous instance"
                             " based on :attr:`{field}`.".format(
                    field=match.group('field')
                ))
