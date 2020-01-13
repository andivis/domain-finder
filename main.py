import time
import datetime
import logging
import sys
import random
import re
import lxml.html as lh
import traceback
import os
import json
import other.helpers as helpers
from other.helpers import Downloader
from other.api import Api
from other.database import Database

class Google:
    def search(self, query, numberOfResults, urlPrefix=None, acceptAll=False):
        self.captcha = False        
        self.searchFailed = False        

        if not urlPrefix:
            urlPrefix = 'https://www.google.com'

        parameters = {
            'q': query,
            'hl': 'en'
        }

        url = urlPrefix + '/search'

        page = self.api.get(url, parameters, False)

        if not page:
            self.searchFailed = True
            return []

        if '--debug' in sys.argv:
            helpers.toFile(page, 'logs/page.html')

        result = self.getSearchResults(page, query, numberOfResults, acceptAll)

        return result

    def getSearchResults(self, page, query, numberOfResults, acceptAll):
        result = ''

        if numberOfResults > 1:
            result = []

        if 'detected unusual traffic from your computer network.' in page:
            logging.error(f'There is a captcha')
            self.captcha = False
            return result

        if 'google.' in page and 'did not match any documents' in page:
            toDisplay = query.replace('+', ' ')
            logging.debug(f'No search results for {toDisplay}')

            if numberOfResults == 1:
                return 'no results'
            else:
                return ['no results']

        xpaths = [
            ["//a[contains(@class, ' ') and (contains(@href, '/url?')  or contains(@ping, '/url?'))]", 'href'],
            ["//a[contains(@href, '/url?') or contains(@ping, '/url?')]", 'href']
        ]

        document = lh.fromstring(page)

        for xpath in xpaths:
            elements = self.downloader.getXpathInElement(document, xpath[0], False)

            attribute = xpath[1]

            for element in elements:
                url = element

                if not attribute:
                    url = element.text_content()
                else:
                    url = element.attrib[attribute]

                if self.shouldAvoid(url, acceptAll):
                    continue

                if numberOfResults == 1:
                    result = url
                    break
                else:
                    result.append(url)

                    if len(result) >= numberOfResults:
                        break

            if numberOfResults == 1 and result:
                break
            elif len(result) >= numberOfResults:
                break

        return result

    def shouldAvoid(self, url, acceptAll):
        result = False

        if not url:
            return True

        # avoids internal links
        if not url.startswith('http:') and not url.startswith('https:'):
            return True

        if helpers.substringIsInList(self.avoidPatterns, url):
            return True

        if not acceptAll:
            if helpers.substringIsInList(self.userAvoidPatterns, url):
                logging.debug(f'Avoiding {url}. It\'s in userAvoidPatterns.')
                return True

            if self.domainMatchesList(url, self.userAvoidDomains):
                logging.debug(f'Avoiding {url}. It\'s in userAvoidDomains.')
                return True

            if self.domainMatchesList(url, self.avoidDomains):
                logging.debug(f'Avoiding {url}. It\'s in avoidDomains.')
                return True

        return result

    def domainMatchesList(self, url, list):
        result = False
        
        domain = helpers.getDomainName(url)

        if domain in list:
            logging.debug(f'Skipping. Domain is {domain}.')
            return True

        for item in list:
            toFind = f'.{item}'
            
            if domain.endswith(toFind):
                logging.debug(f'Skipping. Domain ends with {item}.')
                return True

        return result

    def __init__(self):
        self.api = Api('')
        self.downloader = Downloader()
        self.proxies = None
        self.captcha = False
        self.avoidDomains = []
        self.userAvoidPatterns = []
        self.userAvoidDomains = []


class DomainFinder:
    def find(self, item):
        result = {}

        self.captcha = False
        self.searchFailed = False

        suffix = ' -https://companieshouse.gov.uk/ -https://www.linkedin.com/'
        addressPart = self.getAddressForQuery(item)

        # try with and without quotes
        queries = [
            self.getQuery(item) + f' {addressPart} {suffix}',
            item.get('Company Name', '') + f' {addressPart} {suffix}',
            item.get('Company Name', '')
        ]

        urls = []

        for query in queries:
            urlsForQuery = self.search(query, 20)

            urls = self.addIfNew(urls, urlsForQuery)

            if self.captcha or self.searchFailed:
                return {}

        measurementTypes = ['quick', 'detailed']

        # do a quick check and if necessary, a detailed check
        for measurementType in measurementTypes:
            result = self.checkUrls(urls, item, measurementType)

            if self.captcha:
                return {}

            if result:
                break

        if not result:
            # could not find a result
            result = {
                'url': 'none',
                'confidence': 0,
                'maximumPossibleConfidence': -1
            }

        fullName = item.get('Company Name', '')
        url = result.get('url', '')
        
        logging.info(f'Result for {fullName}: {url}. Confidence {self.confidence} out of {self.maximumPossibleConfidence}.')

        return result

    def addIfNew(self, existingList, newList):
        result = existingList

        for item in newList:       
            if not item in existingList:
                result.append(item)

        return result

    def checkUrls(self, urls, item, measurementType):
        result = {}

        minimumConfidenceToStopLooking = 500
        maximumDetailedTries = 7

        if '--debug' in sys.argv:
            maximumDetailedTries = 4

        previousDomain = ''

        logging.debug(f'Measurement type: {measurementType}')
            
        i = 0
        tries = 0
        maximumConfidenceFoundSoFar = 0

        # try several url's if necessary
        for url in urls:
            self.testsPassed = 0
            self.totalTests = 0
            self.confidence = 0
            self.maximumPossibleConfidence = 0

            if measurementType == 'detailed' and tries >= maximumDetailedTries:
                logging.debug(f'Stopping. Tried {tries} times in detailed mode.')
                break

            if not url:
                i += 1
                continue

            if url == 'no results':
                continue

            domain = helpers.getDomainName(url)

            if domain == previousDomain:
                continue

            previousDomain = domain

            logging.debug(f'Trying result {i + 1} of {len(urls)}: {domain}')

            self.measureConfidence(item, url, domain, measurementType)

            tries += 1

            if self.captcha:
                return {}
                
            if self.confidence < self.minimumConfidence:
                logging.info(f'Confidence is only {self.confidence}. Trying next candidate. On {i + 1} of {len(urls)}.')
                i += 1
                continue

            # choose the best candidate
            if self.confidence > maximumConfidenceFoundSoFar:
                result = {
                    'url': self.getMainPart(url),
                    'confidence': self.confidence,
                    'maximumPossibleConfidence': self.maximumPossibleConfidence
                }

                maximumConfidenceFoundSoFar = self.confidence

            if self.confidence >= minimumConfidenceToStopLooking:
                logging.info(f'Confidence is at least {minimumConfidenceToStopLooking}. Not checking more candidates.')
                break

        return result

    def search(self, query, numberOfResults, acceptAll=False):
        logging.debug(f'Searching for: {query}')

        self.google.api.proxies = self.getRandomProxy()

        searchUrl = self.defaultSearchUrl

        result = self.google.search(query, numberOfResults, searchUrl, acceptAll)

        self.handleErrors(result)

        return result

    def measureConfidence(self, item, url, domain, measurementType):
        self.api.proxies = self.getRandomProxy()

        veryBasicDomain = helpers.findBetween(domain, '', '.')
        veryBasicDomain = veryBasicDomain.replace('-', '')

        self.basicDomain = domain

        basicName = item.get('Company Name', '').lower()
        basicName = basicName.strip()
        
        filteredName = self.getFilteredName(item)

        score = 0        
        
        if domain.endswith(self.preferredDomain):
            score = 200

        self.increaseConfidence(score, 200, f'The domain ends in {self.preferredDomain}.', f'domain ends in {self.preferredDomain}')

        # does the domain name contain the company name?
        self.domainContainsRightWords(item, veryBasicDomain)

        # don't need to check everything in some cases
        if measurementType == 'quick':
            return

        # given company's address is on the site?
        score = 0
        address = item.get('Registered Address', '')
        #remove care of
        if 'c/o' in address.lower():
            address = helpers.findBetween(address, ', ', '')

        addressSearch = self.search(f'site:{domain} {address}', 1, False)
        if addressSearch and addressSearch != 'no results':
            score = 250

        self.increaseConfidence(score, 250, f'The registered address appears on {url}.', 'address on website')

        self.checkWhois(domain, filteredName)

        self.checkExternalDomains(domain, basicName)

        # title of the site has the given company name?
        page = self.api.getPlain(url)
        title = self.downloader.getXpath(page, "//title", True)

        if filteredName in title.lower():
            self.increaseConfidence(200, 200, 'Found {filteredName} in title of {url}', 'website title')
        else:
            words = self.getWordsInName(basicName)
            maximumRun = self.wordsInARowTheSame(words, title, ' ', False)

            self.increaseConfidence(maximumRun * 100, len(words) * 100, f'The title of {url} has {maximumRun} out of {len(words)} words in a row the same as {filteredName}. Title: {title}.', 'website title')

            score = 0

            if len(words) >= 2 and maximumRun == len(words):
                score = 100

            self.increaseConfidence(score, 100, f'All words in website title match.', 'website title')

        score = 0

        if self.checkApi(item) == domain:
            score = 175

        self.increaseConfidence(score, 175, 'The domain from Google matches the domain from another service.', 'check')

    def checkExternalDomains(self, domain, basicName):
        # does the company have social media pages?
        externalDomains = [
            'facebook.com',
            'instagram.com',
            'twitter.com'
        ]

        for externalDomain in externalDomains:
            self.checkExternalDomain(externalDomain, basicName, domain)

    def getWebsiteLinksInSocialMediaPage(self, url):
        results = []

        xpaths = {
            'facebook.com': "//a[@target = '_blank' and not(contains(@href, 'facebook.com/'))]"
        }

        socialMediaDomain = helpers.getDomainName(url)

        xpath = xpaths.get(socialMediaDomain, '')

        if not xpath:
            return results

        page = self.api.getPlain(url)
        results = self.downloader.getXpath(page, xpath, True, 'href')

        return results

    def getQuery(self, item):
        name = item.get('Company Name', '').lower()
        # in case a space is missing
        name = name.replace(',', ', ')
        name = name.strip()
        name = self.squeezeWhitespace(name)

        # quote parts before these        
        stringsToIgnore = [
            ' limited',
            ' ltd',
            ' llc',
            ' inc',
            ' incorporated',
            ' (',
            '('
        ]

        minimumIndex = len(name)

        for string in stringsToIgnore:
            if string in name:
                index = name.index(string)

                if index < minimumIndex:
                    minimumIndex = index
                    
        name = self.insert(name, minimumIndex, '" ')
        name = '"' + name
        name = self.squeezeWhitespace(name)

        return name

    def getAddressForQuery(self, item):
        address = item.get('Registered Address', '')
        address = address.strip()

        list = [
            'england',
            'united kingdom',
            'uk',
            'u.k.'
        ]

        address = self.getPartBeforeList(list, address)

        return address

    def getPartBeforeList(self, list, s):
        minimumIndex = len(s)

        for string in list:
            if string in s.lower():
                index = s.lower().index(string)

                if index < minimumIndex:
                    minimumIndex = index
                    
        s = s[0:minimumIndex]
        s = s.strip()

        if s.endswith(','):
            s = s[0:-1]

        return self.squeezeWhitespace(s)

    def squeezeWhitespace(self, s):
        return re.sub(r'\s\s+', " ", s)
    
    def insert(self, string, index, toInsert):
        return string[:index] + toInsert + string[index:]

    def checkExternalDomain(self, domain, basicName, urlToFind):
        score = 0
        numberOfResults = 3

        logging.debug(f'Checking {domain}')

        if '--debug' in sys.argv:
            numberOfResults = 2

        urls = self.search(f'site:{domain} {basicName}', numberOfResults, True)

        matchingUrl = ''

        # check if those pages contain a given domain
        for url in urls:
            if url == 'no results':
                break

            self.api.proxies = self.getRandomProxy()

            if self.urlContainsText(url, urlToFind):
                matchingUrl = url
                score = 300
                break

        self.increaseConfidence(score, 300, f'The company\'s page on {domain} seems to be {matchingUrl} and it contains {urlToFind}.', f'{domain} page')

    def checkWhois(self, domain, filteredName):
        score = 0

        urls = [
            f'https://www.namecheap.com/domains/whoislookup-api/{domain}',
            f'https://www.whois.com/whois/{domain}',
            f'https://who.is/whois/{domain}'
        ]

        url = random.choice(urls)

        logging.debug('Checking {url}')

        page = self.api.getPlain(url)

        # to avoid false matches
        page = page.replace(domain, '')

        if not 'domain name:' in page.lower():
            logging.debug(f'It seems {url} didn\'t return any whois information')

        if filteredName in page.lower():
            score = 300

        self.increaseConfidence(score, 300, f'The whois record for {domain} contains {filteredName}.', 'whois')

    def urlContainsText(self, url, text):
        page = self.api.getPlain(url)

        return text in page.lower()

    def checkApi(self, item):
        result = ''

        name = self.getFilteredName(item)

        api = Api('https://autocomplete.clearbit.com')

        response = api.get(f'/v1/companies/suggest?query={name}')

        if response and len(response) > 0:
            result = response[0].get('domain', '')

        return result

    def increaseConfidence(self, number, maximumPossible, message, shortMessage):
        self.maximumPossibleConfidence += maximumPossible
        self.totalTests += 1

        word = 'failed'

        if number == 0:
            logging.debug(f'Confidence: {self.confidence} out of {self.maximumPossibleConfidence}. Failed: {message}')
        else:
            word = 'passed'
            
            self.testsPassed += 1

            self.confidence += number

            logging.debug(f'Confidence: {self.confidence} out of {self.maximumPossibleConfidence}. Added {number}. Passed: {message}')

        logging.info(f'Domain: {self.basicDomain}. Tests passed: {self.testsPassed} of {self.totalTests}. Test {word}: {shortMessage}.')

    def getWordsInName(self, name):
        wordsToIgnore = [
            'limited',
            'ltd',
            'llc',
            'inc',
            'incorporated'
        ]

        words = re.sub(r'[^\w]', ' ',  name).split()

        for word in wordsToIgnore:
            if word in words:
                words.remove(word)

        return words

    def getFilteredName(self, item):
        name = item.get('Company Name', '')
        words = self.getWordsInName(name)

        return ' '.join(words)

    def wordsInARowTheSame(self, words, toCompare, joinString, mustStartWith):
        result = 0

        toCompare = toCompare.lower()

        # try longest run first, then try smaller ones
        for i in range(len(words), -1, -1):
            line = joinString.join(words[0:i])

            if mustStartWith:
                if toCompare.startswith(line) and i > result:
                    result = i
                    break            
            else:
                if line in toCompare and i > result:
                    result = i
                    break

        return result

    def domainContainsRightWords(self, item, url):
        name = item.get('Company Name', '').lower()
        name = name.strip()
        name = name.replace('&', ' and ')
        name = self.squeezeWhitespace(name)

        types = ['regular', 'abbreviations', 'initials']

        maximumScore = 0
        maximumRun = 0
        words = self.getWordsInName(name)        
        wordLengthForMaximum = len(words)

        # check both regular words and abbreviations. choose the highest scoring one.
        for type in types:
            # reset it in case it changed
            words = self.getWordsInName(name)

            if type == 'abbreviations':
                words = self.getAbbreviations(words)
            if type == 'initials':
                if len(words) < 2:
                    continue

                words = self.getInitials(words)

            object = self.domainContainsRightWordsByType(words, url, type)

            if object['score'] > maximumScore:
                maximumScore = object['score']
                maximumRun = object['maximumRun']
                wordLengthForMaximum = len(words)
        
        if maximumRun == wordLengthForMaximum:
            self.increaseConfidence(maximumScore, 500, f'All words match.', 'domain matches company name')
        else:
            self.increaseConfidence(maximumScore, wordLengthForMaximum * 300, f'{url} has {maximumRun} out of {wordLengthForMaximum} words in a row the same as {name}.', 'domain similar to company name')

    def domainContainsRightWordsByType(self, words, url, type):
        score = 0

        # exact match?
        if ''.join(words) == url:
            score = 500

        if score > 0:
            result = {
                'score': score,
                'maximumRun': len(words)
            }

            return result

        score = 0
        
        # is similar at least?
        # try to find matchings run starting at word 1, then word 2, etc.
        for i in range(0, len(words)):
            mustStartWith = False

            if type == 'initials':
                mustStartWith = True

            maximumRun = self.wordsInARowTheSame(words[i:], url, '', mustStartWith)

            # url must start the initials
            if type == 'initials' and i > 0:
                break

            if maximumRun:
                break

        # want at least 2 initials in a row
        if type == 'initials' and maximumRun < 2:
            maximumRun = 0
        
        score = maximumRun * 300

        result = {
            'score': score,
            'maximumRun': maximumRun
        }
        
        return result

    def getAbbreviations(self, words):
        result = []

        abbreviations = {
            'system': 'sys',
            'systems': 'sys',
            'company': 'co'
        }

        for word in words:
            if word in abbreviations:
                result.append(abbreviations[word])
            else:
                result.append(word)

        return result

    def getInitials(self, words):
        result = []

        ignore = [
            'and',
            '&',
            'the',
            'of',
            'if',
            'by',
            'to'
        ]

        for word in words:
            if not word in ignore and len(word) > 0:
                result.append(word[0])
            else:
                result.append(word)

        return result

    def handleErrors(self, result):
        if result == '':
            logging.info('Skipping this item. A search failed.')
            self.searchFailed = True

        # so calling class knows it needs to retry
        if self.google.captcha:
            logging.info('Skipping this item. Captcha during search.')
            self.captcha = True

    def getMainPart(self, url):
        result = url

        fields = url.split('/')

        if len(fields) >= 3:
            result = '/'.join(fields[0:3])

        return result

    def getProxiesFromApi(self):
        result = None

        externalApi = Api('')
        apiKey = externalApi.getPlain(self.proxyListUrl)

        if not apiKey:
            return result

        api = Api('https://api.myprivateproxy.net')

        # get allowed ip's
        allowedIps = api.get(f'/v1/fetchAuthIP/{apiKey}')

        if not allowedIps:
            return result

        ipInfoApi = Api('')

        currentIp = ipInfoApi.get('https://ipinfo.io/json')

        if not currentIp or not currentIp.get('ip', ''):
            logging.error('Can\'t find current ip address')
            return result

        currentIp = currentIp.get('ip', '')

        # check if it's already allowed
        if not currentIp in allowedIps:
            toKeep = 3
            newAllowedIps = allowedIps[0:toKeep]
            newAllowedIps.append(currentIp)

            # add current ip to allowed ip's
            response = api.post(f'/v1/updateAuthIP/{apiKey}', json.dumps(newAllowedIps))

            if response.get('result', '') != 'Success':
                logging.error('Failed to update allowed ip addresses')

        response = api.get(f'/v1/fetchProxies/json/full/{apiKey}')

        if not response:
            return result

        result = []

        for item in response:
            newItem = {
                'url': item.get('proxy_ip', ''),
                'port': item.get('proxy_port', ''),
                'username': item.get('username', ''),
                'password': item.get('password', ''),
            }

            result.append(newItem)

        return result

    def getRandomProxy(self):
        if not self.proxies:
            if os.path.exists('proxies.csv'):
                self.proxies = helpers.getCsvFileAsDictionary('proxies.csv')
            elif self.proxyListUrl:            
                self.proxies = self.getProxiesFromApi()

            if not self.proxies:
                logging.info('No proxies found')

        if not self.proxies:
            return None

        item = random.choice(self.proxies)

        url = item.get('url', '')
        port = item.get('port', '')
        userName = item.get('username', '')
        password = item.get('password', '')

        proxy = f'http://{userName}:{password}@{url}:{port}'

        if not userName or not password:
            proxy = f'http://{url}:{port}'

        proxies = {
            'http': proxy,
            'https': proxy
        }

        logging.debug(f'Using proxy http://{url}:{port}')

        return proxies

    def __init__(self, options):
        self.api = Api('')
        self.downloader = Downloader()
        self.google = Google()
        self.proxies = None
        self.defaultSearchUrl = options.get('defaultSearchUrl', '')
        self.captcha = False
        self.searchFailed = False
        self.minimumConfidence = options.get('minimumConfidence', '')
        self.preferredDomain = options.get('preferredDomain', '')
        self.proxyListUrl = options.get('proxyListUrl', '')
        self.testsPassed = 0
        self.totalTests = 0
        self.confidence = 0
        self.maximumPossibleConfidence = 0

        file = helpers.getFile('resources/top-domains.csv')
        self.google.avoidDomains = file.splitlines()

        self.google.avoidPatterns = [
            'webcache.googleusercontent.com',
            'google.'
        ]

        # set by the user
        if options.get('ignorePatterns', ''):
            self.google.userAvoidPatterns = options['ignorePatterns']

        if options.get('ignoreDomains', ''):
            self.google.userAvoidDomains = options['ignoreDomains']

class Main:
    def run(self):
        self.initialize()

        self.sliceItems()

        while True:
            self.tryIteration()
            
            logging.info(f'Done {self.itemsDone} of {len(self.items)}')
            
            if self.itemsDone >= len(self.items):
                logging.info(f'Done all items')
                break
            else:
                logging.info(f'Don\'t have all the results yet. Will try again in a few seconds.')
                time.sleep(10)

        self.cleanUp()

    def tryIteration(self):
        self.onItemIndex = 0
        self.itemsDone = 0
        
        for item in self.items:
            try:
                self.doItem(item)
            except Exception as e:
                logging.error(f'Skipping. Something went wrong: {e}')
                logging.debug(traceback.format_exc())

            self.onItemIndex += 1

    def combine(self):
        logging.info('Combining results from all threads')

        outputFile = self.options['outputFile']

        helpers.removeFile(outputFile)
        
        while True:
            itemsFound = 0

            for item in self.items:
                try:
                    id = item.get('Company Number', '')

                    if not id:
                        continue
                    
                    row = self.database.getFirst('history', '*', f"id = '{id}'", '', '')

                    if not row:
                        continue

                    fields = {
                        'url': row.get('result', ''),
                        'confidence': row.get('confidence', ''),
                        'maximumPossibleConfidence': row.get('maximumPossibleConfidence', '')
                    }

                    self.outputResult(item, fields, True)

                    itemsFound += 1
                except Exception as e:
                    logging.error(f'Skipping. Something went wrong: {e}')
                    logging.debug(traceback.format_exc())

            logging.info(f'Wrote {itemsFound} of {len(self.items)} to {outputFile}')
            
            if itemsFound >= len(self.items):
                logging.info(f'Wrote all items')
                break
            else:
                logging.info(f'Don\'t have all the results yet. Will check again in a few seconds.')
                time.sleep(10)

        self.cleanUp()

    def doItem(self, item):
        self.showStatus(item)

        name = item.get('Company Name', '')

        if not name:
            return

        if self.isDone(item):
            self.itemsDone += 1
            return

        try:
            finderResult = self.domainFinder.find(item)

            if finderResult:
                self.outputResult(item, finderResult)
                self.markDone(item, finderResult)
                self.waitBetween()
                self.itemsDone += 1
        except Exception as e:
            logging.error(f'Skipping. Something went wrong: {e}')

    def sliceItems(self):
        if self.threadCount <= 1:
            return

        start = len(self.items) // self.threadCount * (self.threadNumber - 1)
        end = start + (len(self.items) // self.threadCount)

        if self.threadNumber == self.threadCount or end == 0:
            end = len(self.items)

        self.items = self.items[start:end]
    
    def showStatus(self, item):
        name = item.get('Company Name', '')

        logging.info(
            f'Item {self.onItemIndex + 1} of {len(self.items)}: {name}.')

    def isDone(self, item):
        result = False

        id = item.get('Company Number', '')

        row = self.database.getFirst('history', 'id', f"id = '{id}'", '', '')

        if row:
            logging.info(f'Skipping. Already done this item.')
            result = True

        return result

    def outputResult(self, item, finderResult, force=False):
        if not force and self.threadCount > 1:
            return

        if not os.path.exists(self.options['outputFile']):
            helpers.toFile('Company Number,Company Name,Date Incorporated,Active Directors,Registered Address,Website,Website Confidence', self.options['outputFile'])

        fields = [
            'Company Number',
            'Company Name',
            'Date Incorporated',
            'Active Directors',
            'Registered Address'
        ]
        
        values = []

        for field in fields:
            values.append(item.get(field, ''))

        confidence = finderResult.get('confidence', '')
        maximumPossibleConfidence = finderResult.get('maximumPossibleConfidence', '')
        maximumPossibleConfidence = int(maximumPossibleConfidence)

        percentage = confidence / maximumPossibleConfidence
        percentage = percentage * 100
        percentage = int(round(percentage))

        if finderResult.get('url', '') == 'none':
            percentage = -1

        values.append(finderResult.get('url', ''))
        values.append(percentage)

        self.appendCsvFile(values, self.options['outputFile'])

    def appendCsvFile(self, list, fileName):
        import csv
        with open(fileName, "a", newline='\n', encoding='utf-8') as csv_file:
            writer = csv.writer(csv_file, delimiter=',')
            writer.writerow(list)

    def markDone(self, item, finderResult):
        if not finderResult.get('url', ''):
            return

        item = {
            'id': item.get('Company Number', ''),
            'name': item.get('Company Name', ''),
            'result': finderResult.get('url', ''),
            'confidence': finderResult.get('confidence', ''),
            'maximumPossibleConfidence': finderResult.get('maximumPossibleConfidence', ''),
            'gmDate': str(datetime.datetime.utcnow())
        }

        logging.debug(f'Inserting into database')
        logging.debug(item)

        self.database.insert('history', item)

    def waitBetween(self):
        secondsBetweenItems = self.options['secondsBetweenItems']

        if not secondsBetweenItems:
            return

        logging.info(f'Waiting {secondsBetweenItems} seconds')

        time.sleep(secondsBetweenItems)

    def deleteResultsToAvoid(self):
        rows = self.database.get('history', '*', "result != 'none'", '', '')

        for row in rows:
            url = row.get('result', '')

            shouldDelete = self.domainFinder.google.shouldAvoid(url, False)

            if shouldDelete:
                id = row.get('id', '')
                name = row.get('name', '')

                logging.info(f'Deleting result for {name} because it matches a pattern to ignore. Url: {url}.')

                self.database.execute(f"delete from history where id = '{id}'")

    def cleanUp(self):
        self.database.close()

        logging.info('Done')
        input("Press enter to exit...")

    def initialize(self):
        logFileNameSuffix = ''

        self.threadNumber = helpers.getParameter('--threadNumber', False, 1)
        self.threadCount = helpers.getParameter('--threadCount', False, 1)

        if self.threadCount:
            self.threadNumber = int(self.threadNumber)
            self.threadCount = int(self.threadCount)

            if self.threadNumber > self.threadCount:
                exit()

            if self.threadCount > 1:
                logFileNameSuffix = f'-{self.threadNumber}'

        helpers.setUpLogging(logFileNameSuffix)

        logging.info('Starting\n')

        self.onItemIndex = 0

        self.database = Database('database.sqlite')
        self.database.execute('create table if not exists history ( id text, name text, result text, confidence integer, maximumPossibleConfidence integer, gmDate text, primary key(id) )')

        # set default options
        self.options = {
            'inputFile': 'input.csv',
            'outputFile': 'output.csv',
            'secondsBetweenItems': 3,
            'maximumDaysToKeepItems': 90,
            'defaultSearchUrl': '',
            'minimumConfidence': 500,
            'preferredDomain': '',
            'ignorePatterns': '',
            'ignoreDomains': '',
            'proxyListUrl': helpers.getFile('resources/resource')
        }

        if '--debug' in sys.argv:
            self.options['secondsBetweenItems'] = 0

        # read the options file
        helpers.setOptions('options.ini', self.options)

        self.options['ignorePatterns'] = self.options['ignorePatterns'].split(',')
        self.options['ignoreDomains'] = self.options['ignoreDomains'].split(',')

        self.domainFinder = DomainFinder(self.options)

        self.items = helpers.getCsvFileAsDictionary(self.options['inputFile'])

        self.deleteResultsToAvoid()

        if not '--debug' in sys.argv:
            random.shuffle(self.items)

        if '--combine' in sys.argv:
            self.combine()
            exit()


main = Main()
main.run()
