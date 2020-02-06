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
from django.db.models import Count

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
    case_num_pat = re.compile("[A-Z0-9]{1,4}-.*")
    # loop now inside function -- count is passed to function
    # case_list = []
    # for filename in glob.glob('/Users/efstone/Downloads/eviction_cases/*-*.html'):
    #     case_list.append(os.path.split(filename)[1][:-5])
    for i in range(1, num_runs):
        start_date_text = CaseConfig.objects.get(eviction_key='start_date')
        start_date_as_date = datetime.strptime(start_date_text.eviction_value, "%m/%d/%Y")
        start_date = pytz.timezone('US/Central').localize(start_date_as_date)
        # Create a new instance of the Firefox driver (also opens FireFox)
        if start_date > timezone.now():
            break
        driver.get("http://justice1.dentoncounty.com/PublicAccess/default.aspx")
        Select(driver.find_element_by_id("sbxControlID2")).select_by_visible_text(f"{CaseConfig.objects.get(eviction_key='court_type').eviction_value}")
        # Select(driver.find_element_by_id("sbxControlID2")).select_by_visible_text("Justice of the Peace Pct #4")
        # for civil records
        driver.find_element_by_link_text(f"{CaseConfig.objects.get(eviction_key='case_type').eviction_value}").click()
        # for criminal records
        # driver.find_element_by_link_text("JP & County Court: Criminal Case Records").click()
        driver.find_element_by_id("DateFiled").click()
        driver.find_element_by_id("DateFiledOnAfter").clear()
        driver.find_element_by_id("DateFiledOnAfter").send_keys((start_date + timedelta(days=1)).strftime("%m/%d/%Y"))
        driver.find_element_by_id("DateFiledOnBefore").clear()
        driver.find_element_by_id("DateFiledOnBefore").send_keys((start_date + timedelta(days=3)).strftime("%m/%d/%Y"))
        print(f'checking range {(start_date + timedelta(days=1)).strftime("%m/%d/%Y")} - {(start_date + timedelta(days=3)).strftime("%m/%d/%Y")}')
        driver.find_element_by_id("SearchSubmit").click()
        # grabbing eviction links with bs4
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        print(f'found {len(soup.find_all("a", text=case_num_pat))} links')
        for link in soup.find_all("a", text=case_num_pat):
            print(f"checking case {link.text}")
            if len(link.text) > 0 and re.match(case_num_pat, link.text) is not None:
                if Case.objects.filter(case_num=link.text).count() == 0:
                    print(f"downloading case {link.text}")
                    driver.get("http://justice1.dentoncounty.com/PublicAccess/" + link.get('href'))
                    case = Case()
                    case.page_source = driver.page_source
                    case.case_num = link.text
                    cur_case_soup = BeautifulSoup(driver.page_source, "html.parser")
                    # print(link.text)
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
            print(start_date.strftime("%m/%d/%Y") + ' returned too many records')
        start_date_text.eviction_value = (start_date + timedelta(days=3)).strftime("%m/%d/%Y")
        start_date_text.save()
    driver.quit()


@app.task
def parse_case(**kwargs):
    run_queries = kwargs.get('run_queries', False)
    if run_queries is True:
        with connection.cursor() as cursor:
            # extract case type
            cursor.execute("UPDATE denton_docket_case SET case_type = (regexp_match(page_source, '(?:Case Type:.*?<b>)(.*?)<\/b>'))[1] WHERE case_type = '' AND page_source ~ 'Case Type:.*?<b>.*?<\/b>';")
            # extract court
            cursor.execute("UPDATE denton_docket_case SET court = (regexp_match(page_source, '(?:Location:.*?<b>)(.*?)<\/b>'))[1] WHERE court = '' AND page_source ~ 'Location:.*?<b>.*?<\/b>';")
            # extract judge
            cursor.execute("UPDATE denton_docket_case SET judge = (regexp_match(page_source, '(?:Judicial Officer:.*?<b>)(.*?)<\/b>'))[1] WHERE judge = '' AND page_source ~ 'Judicial Officer:.*?<b>.*?<\/b>';")
    total_cases = Case.objects.count()
    iterations = int(round(total_cases / 10000)) + 1
    for i in range(iterations):
        for cnum, case in enumerate(Case.objects.filter(appearance__party=None)[:10000]):
            soup = BeautifulSoup(case.page_source, 'html.parser')
            # disposition extractor was here -- please redo it in SQL
            for idx, row in enumerate(soup.find_all(id=re.compile("PIr"))):
                if idx == 0:
                    ptype = row.get_text()
                if idx % 2 == 0:
                    ptype = row.get_text()
                else:
                    party = Party.objects.get_or_create(name=row.get_text())[0]
                    appearance = Appearance(case=case, party=party, party_type=ptype)
                    try:
                        appearance.save()
                    except Exception as e:
                        print(f"error saving appearance for case: {case.case_num}; appearance: {party.name} as {ptype}\n{e}")
                    # attorney finder
                    if row.parent.find('i') is not None:
                        if row.parent.find('i').get_text() == 'Retained':
                            attorney = Attorney.objects.get_or_create(name=row.parent.find('i').parent.find('b').get_text())[0]
                            appearance.attorney_set.add(attorney)
                            attorney.save()
            if cnum % 100 == 0:
                print(f"{case.case_num} - {case.case_type} - {case.court} - {case.parties()}")


