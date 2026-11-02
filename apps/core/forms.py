from django.forms.renderers import TemplatesSetting


class FormRenderer(TemplatesSetting):
    form_template_name = "components/forms/form.html"
    field_template_name = "components/forms/field.html"
