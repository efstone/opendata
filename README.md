# opendata 
## Evictions
### History and Purporse
The "evictions" Django app within this project is a more developed version of a pet project I started to determine bias in eviction cases in Denton County, TX. The project involves scraping public court dockets for Denton County, then parsing out relevant fields of data and loading them into a database for further analysis. Because the focus was on eviction cases, the primary target of scraping was the Justice of the Peace Courts (JP Courts). The project was briefly worked on by a small team during Open Data Day in Dallas County, at the downtown Dallas Public Library. 
### How it works
#### Overview
* This is a Python web scraping project, with hardcoded URLs, but variable search vectors. 
* Key components
  * **Django** as the ORM
  * **PostgreSQL** as the database
  * **BeautifulSoup** to parse the web pages (and some postgres-specific SQL)
  * **Chromium** as the browser, because many sites fend off simple non-browser calls from Python libraries like requests
  * **Selenium** to serve as the webdriver for controlling Chromium
  * **Celery** to manage the tasks, which run over long periods of time
  * Linux VPS (that's what I mainly use it on)
* using the Config model, specify parameters as needed, e.g. search_range (number of days for one search--3 seems optimal), court_choice_list, case_type_list and start_date
* ensure Celery is running and that it loaded your tasks
* launch the django shell
* import everything from utils.py
* run docket_eater, usually with the delay method to ensure it's handled by Celery
* when the pages have finished downloading, run the parsing routine
## Knapiks
This is Minecraft chat project that should probably be in its own repo, because it really has nothing to do with Open Data Day. You're welcome to check it out. It lets you txt back and forth with Minecraft players via SMS message from your phone. (you need control of the server in question, obviously, as it relies on FTP and RCON)
