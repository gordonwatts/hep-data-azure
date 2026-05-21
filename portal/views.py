from django.shortcuts import render


def home(request):
    return render(request, "portal/home.html", {"page_title": "Plot Portal"})

