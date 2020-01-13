import sys
import io
import logging
import os.path
import csv
import subprocess
import random
import time
import configparser
import datetime
import json
import traceback
from collections import OrderedDict
from . import helpers

class Api:
    def get(self, url, parameters={}, responseIsJson=True):
        import requests

        result = ''

        if responseIsJson:
            result = {}

        try:
            logging.debug(f'Get {url}')

            verify = True
            
            fileName = ''
            
            if '--debug' in sys.argv:
                logging.debug(f'Request headers: {self.headers}')

                if self.proxies and 'localhost:' in self.proxies.get('http', ''):
                    verify = False

                fileName = self.getCacheFileName(url)

                if not '--noCache' in sys.argv and os.path.exists(fileName):
                    logging.info('Using cached version')
                    result = helpers.getFile(fileName)

                    if responseIsJson:
                        result = json.loads(result)

            response = requests.get(self.urlPrefix + url, params=parameters, headers=self.headers, proxies=self.proxies, timeout=15, verify=verify)

            if '--debug' in sys.argv and response and response.content:
                logging.debug(f'Response headers: {response.headers}')
                logging.debug(f'Response: {response.text[0:500]}...')
                
                if not ('maps.google' in self.urlPrefix and 'INVALID_REQUEST' in response.text):
                    helpers.toBinaryFile(response.content, fileName)
                    helpers.appendToFile(f'{fileName} {url}', 'logs/cache.txt')

            if responseIsJson:
                result = json.loads(response.text)
            else:
                result = response.text
        
        except Exception as e:
            logging.error(f'Something went wrong: {e}')
            logging.debug(traceback.format_exc())
        
        return result

    def getPlain(self, url):
        return self.get(url, {}, False)

    def post(self, url, data, responseIsJson=True):
        import requests
        
        result = {}

        if not responseIsJson:
            result = ''

        try:
            logging.debug(f'Post {url}')

            verify = True
            
            fileName = ''
            
            if '--debug' in sys.argv:
                logging.debug(f'Request headers: {self.headers}')
                logging.debug(f'Request body: {data}')
                
                if self.proxies and 'localhost:' in self.proxies.get('http', ''):
                    verify = False
                
                # don't want to read files for post, just write them
                fileName = self.getCacheFileName(url)

            response = requests.post(self.urlPrefix + url, headers=self.headers, proxies=self.proxies, data=data, timeout=15, verify=verify)

            if '--debug' in sys.argv and response and response.content:
                logging.debug(f'Response headers: {response.headers}')
                logging.debug(f'Response: {response.text[0:500]}...')
                helpers.toBinaryFile(response.content, fileName)

            if responseIsJson:
                result = json.loads(response.text)
            else:
                result = response.text
        except Exception as e:
            logging.error(f'Something went wrong: {e}')
            logging.debug(traceback.format_exc())

        return result

    def getCacheFileName(self, url):
        result = ''

        file = helpers.getFile('logs/cache.txt')

        for line in file.splitlines():
            fileName = helpers.findBetween(line, '', ' ')
            lineUrl = helpers.findBetween(line, ' ', '')

            if lineUrl == url:
                result = fileName
                break

        if not result:
            fileName = helpers.lettersAndNumbersOnly(url)
            fileName = fileName[0:25]
            
            for i in range(0, 16):  
                fileName += str(random.randrange(0, 10))
            
            result = f'logs/cache/{fileName}.json'

        helpers.makeDirectory('logs/cache')

        return result

    def getHeadersFromTextFile(self, fileName):
        result = OrderedDict()

        lines = helpers.getFile(fileName).splitlines()

        list = []
        cookies = []

        foundCookie = False

        for line in lines:
            name = helpers.findBetween(line, '', ': ')
            value = helpers.findBetween(line, ': ', '')

            if name.lower() == 'cookie':
                if not foundCookie:
                    foundCookie = True                    
                else:
                    cookies.append(value)
                    continue
            
            item = (name, value)

            list.append(item)

        if list:
            result = OrderedDict(list)

            if foundCookie and cookies:
                result['cookie'] += '; ' + '; '.join(cookies)

        return result

    def setHeadersFromHarFile(self, harFileName, urlMustContain):
        try:
            from haralyzer import HarParser
        
            file = helpers.getFile(harFileName)

            j = json.loads(file)

            har_page = HarParser(har_data=j)

            headers = []

            # find the right url
            for page in har_page.pages:
                for entry in page.entries:
                    if urlMustContain in entry['request']['url']:
                        for header in entry['request']['headers']:
                            name = header.get('name', '')

                            # ignore pseudo-headers
                            if name.startswith(':'):
                                continue

                            if name.lower() == 'content-length' or name.lower() == 'host':
                                continue

                            newHeader = (name, header.get('value', ''))

                            headers.append(newHeader)

            self.headers = OrderedDict(headers)
        
        except Exception as e:
            logging.error(f'Something went wrong: {e}')
            logging.debug(traceback.format_exc())

    def getHeadersFromFile(self, fileName):
        file = getFile(fileName)

        if not file:
            return

        j = json.loads(file)

        newHeaders = []

        for header in j.get('headers', ''):
            name = header.get('name', '')

            # ignore pseudo-headers
            if name.startswith(':'):
                continue

            if name.lower() == 'content-length' or name.lower() == 'host':
                continue

            newHeader = (name, header.get('value', ''))

            newHeaders.append(newHeader)

        return OrderedDict(newHeaders)

    def randomizeHeaders(self):
        number = random.randrange(1, 3)

        self.headers = self.getHeadersFromFile(f'resources/headers-{number}.txt')

    def __init__(self, urlPrefix):
        self.urlPrefix = urlPrefix

        self.randomizeHeaders()

        if not self.headers:
            self.userAgentList = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.88 Safari/537.36'
            ]

            userAgent = random.choice(self.userAgentList)

            self.headers = OrderedDict([
                ('user-agent', userAgent),
                ('accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9'),
                ('accept-language', 'en-US,en;q=0.9')
            ])

        self.proxies = None