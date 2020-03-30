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
    court_choice_list = json.loads(CaseConfig.objects.get(key='court_choice_list').value)
    case_type_list = json.loads(CaseConfig.objects.get(key='case_type_list').value)
    search_range = int(CaseConfig.objects.get(key='search_range').value)
    start_date_text = CaseConfig.objects.get(key='start_date')
    start_date_as_date = datetime.strptime(start_date_text.value, "%m/%d/%Y")
    start_date = pytz.timezone('US/Central').localize(start_date_as_date)
    start_url = CaseConfig.objects.get(key='start_url').value
    # loop now inside function -- count is passed to function
    # case_list = []
    # for filename in glob.glob('/Users/efstone/Downloads/eviction_cases/*-*.html'):
    #     case_list.append(os.path.split(filename)[1][:-5])
    for court_choice in court_choice_list:
        for case_type in case_type_list:
            cycle_date = start_date
            for i in range(num_runs):
                # Create a new instance of the Firefox driver (also opens FireFox)
                if cycle_date > timezone.now():
                    break
                driver.get(f"{start_url}default.aspx")
                Select(driver.find_element_by_id("sbxControlID2")).select_by_visible_text(f"{court_choice}")
                # Select(driver.find_element_by_id("sbxControlID2")).select_by_visible_text("Justice of the Peace Pct #4")
                # for civil records
                driver.find_element_by_link_text(f"{case_type}").click()
                # for criminal records
                # driver.find_element_by_link_text("JP & County Court: Criminal Case Records").click()
                driver.find_element_by_id("DateFiled").click()
                driver.find_element_by_id("DateFiledOnAfter").clear()
                driver.find_element_by_id("DateFiledOnAfter").send_keys((cycle_date + timedelta(days=1)).strftime("%m/%d/%Y"))
                driver.find_element_by_id("DateFiledOnBefore").clear()
                driver.find_element_by_id("DateFiledOnBefore").send_keys((cycle_date + timedelta(days=search_range)).strftime("%m/%d/%Y"))
                print(f'checking range {(cycle_date + timedelta(days=1)).strftime("%m/%d/%Y")} - {(cycle_date + timedelta(days=search_range)).strftime("%m/%d/%Y")}')
                driver.find_element_by_id("SearchSubmit").click()
                # grabbing eviction links with bs4
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                print(f'found {len(soup.find_all("a", text=case_num_pat))} links')
                for link in soup.find_all("a", text=case_num_pat):
                    print(f"checking case {link.text}")
                    if len(link.text) > 0 and re.match(case_num_pat, link.text) is not None:
                        if Case.objects.filter(case_num=link.text).count() == 0:
                            print(f"downloading case {link.text}")
                            driver.get(f"{start_url}{link.get('href')}")
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
                    print(cycle_date.strftime("%m/%d/%Y") + ' returned too many records')
                cycle_date = (cycle_date + timedelta(days=search_range))
    start_date_text.value = cycle_date.strftime("%m/%d/%Y")
    start_date_text.save()
    driver.quit()


@app.task
def parse_case(**kwargs):
    run_queries = kwargs.get('run_queries', False)
    if run_queries is True:
        with connection.cursor() as cursor:
            # extract case type
            print("Parsing case type...")
            cursor.execute("UPDATE denton_docket_case SET case_type = (regexp_match(page_source, '(?:Case Type:.*?<b>)(.*?)<\/b>'))[1] WHERE case_type = '' AND page_source ~ 'Case Type:.*?<b>.*?<\/b>';")
            # extract court
            print("Parsing court...")
            cursor.execute("UPDATE denton_docket_case SET court = (regexp_match(page_source, '(?:Location:.*?<b>)(.*?)<\/b>'))[1] WHERE court = '' AND page_source ~ 'Location:.*?<b>.*?<\/b>';")
            # extract judge
            print("Parsing judge...")
            cursor.execute("UPDATE denton_docket_case SET judge = (regexp_match(page_source, '(?:Judicial Officer:.*?<b>)(.*?)<\/b>'))[1] WHERE judge = '' AND page_source ~ 'Judicial Officer:.*?<b>.*?<\/b>';")
            print("Update queries completed.")
    unparsed_cases = Case.objects.filter(parse_time=None)
    total_cases = unparsed_cases.count()
    iterations = int(round(total_cases / 10000)) + 1
    for i in range(iterations):
        print(f"iteration {i} of {iterations}")
        for cnum, case in enumerate(unparsed_cases[:10000]):
            soup = BeautifulSoup(case.page_source, 'html.parser')
            # disposition extractor was here -- please redo it in SQL

            # charge extractor
            try:
                charge = soup.find('th', text=re.compile('Charges: ')).parent.next_sibling.find_all('td')[1].get_text()
                case.first_charge = charge
            except:
                pass
            finally:
                case.parse_time = timezone.now()
                case.save()
            # party + attorney extractor
            if case.party_set.count() == 0:
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
                            if row.parent.find('i') is not None:
                                if row.parent.find('i').get_text() == 'Retained':
                                    attorney = Attorney.objects.get_or_create(name=row.parent.find('i').parent.find('b').get_text())[0]
                                    appearance.attorney_set.add(attorney)
                                    attorney.save()
                        except Exception as e:
                            print(f"error saving appearance/attorney for case: {case.case_num}; appearance: {party.name} as {ptype}\n{e}")
            if CaseConfig.objects.get(key='limit_parse_output').value == 'True':
                if cnum % 100 == 0:
                    print(f"{i}/{cnum}: {case.case_num} - {case.case_type} - {case.court} - {case.parties()}")
            else:
                print(f"{i}/{cnum}: {case.case_num} - {case.case_type} - {case.court} - {case.parties()}")


