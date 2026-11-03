from django.urls import path

from . import views

app_name = "support"

urlpatterns = [
    path("help/", views.faq, name="faq"),
    path("help/contact/", views.contact, name="contact"),
    path("help/contact/sent/", views.contact_sent, name="contact_sent"),
    path("my/tickets/", views.tickets, name="tickets"),
]
