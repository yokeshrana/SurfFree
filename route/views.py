import urllib
import httplib2
from  django.http import request
from django.shortcuts import render
from django.http import HttpResponse

# Create your views here.
def index(request,url):
    conn = httplib2.Http()
    content = conn.request(url, request.method)
    print(content)
    return HttpResponse(content)