from selenium import webdriver
from selenium.webdriver.support.ui import Select
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import re, os, glob, pytz
import requests
from evictions.models import *
from django.db.utils import IntegrityError
from django.utils import timezone
from django.db import connection
import json
import platform
from docketdata.celery import app

if platform.system() == 'Darwin':
    chrome_path = "/Applications/Google Chrome.app/Contents/macOS/Google Chrome"
    driver_path = None
else:
    chrome_path = "/usr/bin/chromium-browser"
    driver_path = '/usr/bin/chromedriver'


@app.task
def docket_eater(num_runs):
    # this function uses the Selenium driver to open the main page of the Denton County court records search
    # and selects the civil dockets for the JP Courts, then enters a 5-day date range based on the last date
    # recorded in a text file in the Documents directory. It then visits each link starting with an "E" for eviction
    # and saves the source of the visited page locally.
    # driver = webdriver.Firefox()
    options = webdriver.ChromeOptions()
    options.binary_location = chrome_path
    options.add_argument('headless')
    options.add_argument('disable-gpu')
    driver = webdriver.Chrome(chrome_options=options)
    # loop now inside function -- count is passed to function
    # case_list = []
    # for filename in glob.glob('/Users/efstone/Downloads/eviction_cases/*-*.html'):
    #     case_list.append(os.path.split(filename)[1][:-5])
    for i in range(1, num_runs):
        last_date = Case.objects.last().filing_date
        # Create a new instance of the Firefox driver (also opens FireFox)
        if last_date > timezone.now():
            break
        driver.get("http://justice1.dentoncounty.com/PublicAccess/default.aspx")
        Select(driver.find_element_by_id("sbxControlID2")).select_by_visible_text("------ All JP Courts ------")
        # Select(driver.find_element_by_id("sbxControlID2")).select_by_visible_text("Justice of the Peace Pct #4")
        # for civil records
        # driver.find_element_by_link_text("JP & County Court: Civil, Family & Probate Case Records").click()
        # for criminal records
        driver.find_element_by_link_text("JP & County Court: Criminal Case Records").click()
        driver.find_element_by_id("DateFiled").click()
        driver.find_element_by_id("DateFiledOnAfter").clear()
        driver.find_element_by_id("DateFiledOnAfter").send_keys((last_date + timedelta(days=1)).strftime("%m/%d/%Y"))
        driver.find_element_by_id("DateFiledOnBefore").clear()
        driver.find_element_by_id("DateFiledOnBefore").send_keys((last_date + timedelta(days=3)).strftime("%m/%d/%Y"))
        driver.find_element_by_id("SearchSubmit").click()
        # grabbing eviction links with bs4
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        for link in soup.find_all("a"):
            if len(link.text) > 0 and re.match('[A-Z0-9]{1,3}-.*', link.text) is not None:
                if Case.objects.filter(case_num=link.text).count() == 0:
                    driver.get("http://justice1.dentoncounty.com/PublicAccess/" + link.get('href'))
                    case = Case()
                    case.page_source = driver.page_source
                    case.case_num = link.text
                    cur_case_soup = BeautifulSoup(driver.page_source, "html.parser")
                    print(link.text)
                    if cur_case_soup.find(string=re.compile("Date Filed")) is not None:
                        filing_date = cur_case_soup.find(string=re.compile("Date Filed")).parent.parent.find('b').get_text()
                        case.filing_date = pytz.timezone('US/Central').localize(datetime.strptime(filing_date, "%m/%d/%Y"))
                    else:
                        print(case.case_num + ': has no filing date')
                    case.save()
                    # with open('/Users/efstone/Downloads/eviction_cases/' + link.text + '.html', 'w') as f:
                    #     f.write(driver.page_source)
        # check for too many records
        if soup.find(string=re.compile("Record Count:")).parent.parent.parent.find_all('b')[1].get_text() == '400':
            print(last_date.strftime("%m/%d/%Y") + ' returned too many records')
    driver.quit()


def parse_case():
    # for case in Case.objects.filter(court=''):
    for case in Case.objects.filter(case_type='Evictions'):
        soup = BeautifulSoup(case.page_source, 'html.parser')
        # display court
        # print(soup.find(string=re.compile("Justice of the Peace Pct")))
        if case.court == '':
            case.court = soup.find(string=re.compile("Location:")).parent.parent.find('b').get_text()
        # display judge
        # print(soup.find(string=re.compile("Judicial Officer")).parent.parent.find('b').get_text())
        if case.judge == '':
            if soup.find(string=re.compile("Judicial Officer")) is not None:
                case.judge = soup.find(string=re.compile("Judicial Officer")).parent.parent.find('b').get_text()
            else:
                print(case.case_num + ': has no judge')
        # display date filed
        # print(soup.find(string=re.compile("Date Filed")).parent.parent.find('b').get_text())
        if case.filing_date is None:
            if soup.find(string=re.compile("Date Filed")) is not None:
                filing_date = soup.find(string=re.compile("Date Filed")).parent.parent.find('b').get_text()
                case.filing_date = pytz.timezone('US/Central').localize(datetime.strptime(filing_date, "%m/%d/%Y"))
            else:
                print(case.case_num + ': has no filing date')
        # case type
        if case.case_type == '':
            case.case_type = soup.find(string=re.compile("Case Type")).parent.parent.find('b').get_text()
        # case disposition
        # print(soup.find(headers=re.compile("RDISPDATE")).parent.parent.find('b').get_text())
        if case.disposition is None:
            try:
                disposition_text = soup.find(headers=re.compile("RDISPDATE")).parent.parent.find('b').get_text()
                disposition = Disposition.objects.get_or_create(name=disposition_text)[0]
                case.disposition = disposition
            except AttributeError:
                pass
        case.save()
        # party finder!!! wooo hooo!
        for idx, row in enumerate(soup.find_all(id=re.compile("PIr"))):
            if idx == 0:
                ptype = row.get_text()
            if idx % 2 == 0:
                ptype = row.get_text()
            else:
                # print(str(ptype) + ': ' + str(row.get_text()))
                party = Party.objects.get_or_create(name=row.get_text())[0]
                # party.cases.add(case)
                case.save()
                a1 = Appearance(case=case, party=party, party_type=ptype)
                a1.save()
                party.save()
                # attorney finder
                if row.parent.find('i') is not None:
                    if row.parent.find('i').get_text() == 'Retained':
                        attorney = Attorney.objects.get_or_create(name=row.parent.find('i').parent.find('b').get_text())[0]
                        attorney.parties.add(party)
                        attorney.cases.add(case)
                        attorney.save()
