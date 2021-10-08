from selenium import webdriver
from bs4 import BeautifulSoup
import re
import pandas as pd


def faculty_parse():
    # launch driver through console for live demo
    driver = webdriver.Firefox()
    driver.get("https://cse.engin.umich.edu/people/faculty/")
    soup = BeautifulSoup(driver.page_source, "html.parser")
    faculty = soup.findAll('div', class_='eecs_person_copy')
    faculty_list = []
    for person in faculty:
        name = person.find('h4').getText()
        email = person.find('a', class_='person_email').getText()
        phone_search = person.find('span', text=re.compile('phone', re.IGNORECASE))
        phone = phone_search.getText()[7:] if phone_search else 'unlisted'
        print(f"{name} -- {email} -- {phone}")
        faculty_list.append([name, email, phone])
    df = pd.DataFrame(faculty_list, columns=['name', 'email', 'phone'])

