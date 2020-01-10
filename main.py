import time
import datetime
import logging
import sys
import random
import re
import lxml.html as lh
import traceback
import os
import helpers
from helpers import Downloader
from helpers import Api
from database import Database


class Google:
    def search(self, query, numberOfResults, urlPrefix=None, acceptAll=False):
        self.captchaOnLastSearch = False
        
        if not urlPrefix:
            urlPrefix = 'https://www.google.com'

        query = query.replace(' ', '+')

        url = urlPrefix + '/search?q=' + query

        page = self.downloader.get(url)

        result = self.getSearchResults(page, query, numberOfResults, acceptAll)

        return result

    def getSearchResults(self, page, query, numberOfResults, acceptAll):
        result = ''

        if numberOfResults > 1:
            result = []

        if 'detected unusual traffic from your computer network.' in page:
            logging.error(f'There is a captcha')
            self.captcha = True
            self.captchaOnLastSearch = False
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
                return True

            domain = helpers.getDomainName(url)

            if domain in self.avoidDomains or domain in self.extraAvoidDomains:
                return True

        return result

    def __init__(self):
        self.downloader = Downloader()
        self.proxies = None
        self.captcha = False
        self.captchaOnLastSearch = False
        self.avoidDomains = []
        self.extraAvoidDomains = []


class DomainFinder:
    def find(self, item):
        result = {
            'url': 'none',
            'confidence': 0,
            'maximumPossibleConfidence': -1
        }

        name = item.get('Company Name', '').lower()
        name = name.strip()

        # reset them
        self.google.extraAvoidDomains = []

        maximumTries = 7

        # try several url's if necessary
        urls = self.search(name, maximumTries, False, False)

        if self.google.captchaOnLastSearch:
            logging.info('Skipping this item. Captcha during search.')
            return {}

        i = 0

        previousDomain = ''

        for url in urls:
            self.testsPassed = 0
            self.totalTests = 0
            self.confidence = 0
            self.maximumPossibleConfidence = 0

            if not url:
                i += 1
                continue

            if url == 'no results':
                logging.error('Skipping. No search results for the company name.')
                break

            domain = helpers.getDomainName(url)
            if domain == previousDomain:
                continue

            previousDomain = domain

            logging.debug(f'Trying result {i + 1} of {len(urls)}: {domain}')

            self.measureConfidence(item, url, domain)

            if self.confidence < self.minimumConfidence:
                logging.info(f'Confidence is only {self.confidence}. Trying next candidate. On {i + 1} of {maximumTries}.')
                self.google.extraAvoidDomains.append(helpers.getDomainName(url))
                i += 1
                continue

            result = {
                'url': self.getMainPart(url),
                'confidence': self.confidence,
                'maximumPossibleConfidence': self.maximumPossibleConfidence
            }

            fullName = item.get('Company Name', '')

            logging.info(f'Result for {fullName}: {domain}. Confidence {self.confidence} out of {self.maximumPossibleConfidence}.')

            break

        return result

    def search(self, query, numberOfResults, acceptAll=False, trimToDomain=True):
        self.google.downloader.proxies = self.getRandomProxy()

        searchUrl = self.defaultSearchUrl

        result = self.google.search(query, numberOfResults, searchUrl, acceptAll)

        self.handleCaptcha()

        if trimToDomain:
            if numberOfResults == 1:
                result = self.getMainPart(result)
            else:
                newResult = []

                for item in result:
                    newResult.append(self.getMainPart(item))

                result = newResult

        return result

    def measureConfidence(self, item, url, domain):
        self.downloader.proxies = self.getRandomProxy()

        veryBasicDomain = helpers.findBetween(domain, '', '.')

        self.basicDomain = domain

        basicName = item.get('Company Name', '').lower()
        basicName = basicName.strip()
        
        filteredName = self.getFilteredName(item)

        score = 0        
        
        if domain.endswith(self.preferredDomain):
            score = 150

        self.increaseConfidence(score, 150, f'The domain ends in {self.preferredDomain}.', f'domain ends in {self.preferredDomain}')

        # does the domain name contain the company name?
        self.domainContainsRightWords(item, veryBasicDomain)

        # given company's address is on the site?
        score = 0
        address = item.get('Registered Address', '')
        #remove care of
        if 'c/o' in address.lower():
            address = helpers.findBetween(address, ', ', '')

        addressSearch = self.search(f'site:{domain} {address}', 1, False, False)
        if addressSearch and addressSearch != 'no results':
            score = 200

        self.increaseConfidence(score, 200, f'The registered address appears on {url}.', 'address on website')

        self.checkWhois(domain, filteredName)

        # does the company have social media pages that link to the given url?
        externalDomains = [
            'facebook.com',
            'instagram.com',
            'twitter.com'
        ]

        for externalDomain in externalDomains:
            self.checkExternalDomain(externalDomain, basicName, domain)

        # title of the site has the given company name?
        page = self.downloader.get(url)
        title = self.downloader.getXpath(page, "//title", True)

        if filteredName in title.lower():
            self.increaseConfidence(200, 200, 'Found {filteredName} in title of {url}', 'website title')
        else:
            words = self.getWordsInName(basicName)
            maximumRun = self.wordsInARowTheSame(words, title, ' ')

            self.increaseConfidence(maximumRun * 50, len(words) * 50, f'The title of {url} has {maximumRun} out of {len(words)} words in a row the same as {filteredName}. Title: {title}.', 'website title')

            score = 0

            if len(words) >= 2 and maximumRun == len(words):
                score = 100

            self.increaseConfidence(score, 100, f'All words in website title match.', 'website title')

        score = 0

        if self.checkApi(item) == domain:
            score = 175

        self.increaseConfidence(score, 175, 'The domain from Google matches the domain from another service.', 'check')

    def checkExternalDomain(self, domain, basicName, urlToFind):
        score = 0
        numberOfResults = 5

        logging.debug(f'Checking {domain}')

        if '--debug' in sys.argv:
            numberOfResults = 2

        urls = self.search(f'site:{domain} {basicName} {urlToFind}', numberOfResults, True, False)

        matchingUrl = ''

        for url in urls:
            if url == 'no results':
                break

            self.downloader.proxies = self.getRandomProxy()

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

        page = self.downloader.get(url)

        # to avoid false matches
        page = page.replace(domain, '')

        if not 'domain name:' in page.lower():
            logging.debug(f'It seems {url} didn\'t return any whois information')

        if filteredName in page.lower():
            score = 300

        self.increaseConfidence(score, 300, f'The whois record for {domain} contains {filteredName}.', 'whois')

    def urlContainsText(self, url, text):
        page = self.downloader.get(url)

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

    def wordsInARowTheSame(self, words, toCompare, joinString):
        result = 0

        toCompare = toCompare.lower()

        # try longest run first, then try smaller ones
        for i in range(len(words), -1, -1):
            line = joinString.join(words[0:i])

            if line in toCompare and i > result:
                result = i
                break

        return result

    def domainContainsRightWords(self, item, url):
        name = item.get('Company Name', '').lower()
        name = name.strip()
        name = replace('&', ' and ')

        score = 0
        words = self.getWordsInName(name)

        # exact match?
        if ''.join(words) == url:
            score = 500

        self.increaseConfidence(score, 500, f'All words match.', 'domain matches company name')
        
        if score > 0:
            return

        score = 0
        
        # is similar at least?
        # try to find matchings run starting at word 1, then word 2, etc.
        for i in range(0, len(words)):
            maximumRun = self.wordsInARowTheSame(words[i:], url, '')

            if maximumRun:
                break

        score = maximumRun * 100

        self.increaseConfidence(score, len(words) * 50, f'{url} has {maximumRun} out of {len(words)} words in a row the same as {name}.', 'domain similar to company name')

    def handleCaptcha(self):
        # so calling class knows it needs to retry
        if self.google.captcha:
            self.captcha = True

    def getMainPart(self, url):
        result = url

        fields = url.split('/')

        if len(fields) >= 3:
            result = '/'.join(fields[0:3])

        return result

    def getRandomProxy(self):
        if not self.proxies:
            if os.path.exists('proxies.csv'):
                self.proxies = helpers.getCsvFileAsDictionary('proxies.csv')
            elif self.proxyListUrl:            
                file = self.downloader.get(self.proxyListUrl)
                helpers.toFile(file, 'resources/list.csv')
                self.proxies = helpers.getCsvFileAsDictionary('resources/list.csv')
                os.remove('resources/list.csv')

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
        self.downloader = Downloader()
        self.google = Google()
        self.proxies = None
        self.defaultSearchUrl = options.get('defaultSearchUrl', '')
        self.captcha = False
        self.minimumConfidence = options.get('minimumConfidence', '')
        self.preferredDomain = options.get('preferredDomain', '')
        self.proxyListUrl = options.get('proxyListUrl', '')

        file = helpers.getFile('resources/top-domains.csv')
        self.google.avoidDomains = file.splitlines()

        self.google.avoidPatterns = [
            'webcache.googleusercontent.com',
            'google.'
        ]

        # set by the user
        self.google.userAvoidPatterns = []

        if options.get('ignorePatterns', ''):
            self.google.userAvoidPatterns += options['ignorePatterns']

        self.extraAvoidDomains = []


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

    def cleanUp(self):
        self.database.close()

        logging.info('Done')
        input("Press enter to exit...")

    def initialize(self):
        logFileNameSuffix = ''

        self.threadNumber = helpers.getArgument('--threadNumber', False, 1)
        self.threadCount = helpers.getArgument('--threadCount', False, 1)

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
            'ignorePatterns': '',
            'preferredDomain': '',
            'proxyListUrl': helpers.getFile('resources/resource')
        }

        if '--debug' in sys.argv:
            self.options['secondsBetweenItems'] = 1

        # read the options file
        helpers.setOptions('options.ini', self.options)

        self.options['ignorePatterns'] = self.options['ignorePatterns'].split(',')

        self.domainFinder = DomainFinder(self.options)

        self.items = helpers.getCsvFileAsDictionary(self.options['inputFile'])

        random.shuffle(self.items)

        if '--combine' in sys.argv:
            self.combine()
            exit()


main = Main()
main.run()
