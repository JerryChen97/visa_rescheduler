# -*- coding: utf8 -*-

import time
import json
import random
import platform
import configparser
from datetime import datetime

import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait as Wait
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

import schedule


config = configparser.ConfigParser()
config.read('config.ini')

USERNAME = config['USVISA']['USERNAME']
PASSWORD = config['USVISA']['PASSWORD']
SCHEDULE_ID = config['USVISA']['SCHEDULE_ID']
COUNTRY_CODE = config['USVISA']['COUNTRY_CODE'] 
FACILITY_ID = config['USVISA']['FACILITY_ID']

SENDGRID_API_KEY = config['SENDGRID']['SENDGRID_API_KEY']
PUSH_TOKEN = config['PUSHOVER']['PUSH_TOKEN']
PUSH_USER = config['PUSHOVER']['PUSH_USER']

LOCAL_USE = config['CHROMEDRIVER'].getboolean('LOCAL_USE')
HUB_ADDRESS = config['CHROMEDRIVER']['HUB_ADDRESS']

TOKEN = config['TELEGRAM']['TOKEN']
CHATID = config['TELEGRAM']['CHATID']

REGEX_CONTINUE = "//a[contains(text(),'Continuar')]"

# def MY_CONDITION(month, day): return int(month) == 11 and int(day) >= 5
def MY_CONDITION(year, month, day): return True # No custom condition wanted for the new scheduled date

STEP_TIME = 0.5  # time between steps (interactions with forms): 0.5 seconds
RETRY_TIME = 60*10  # wait time between retries/checks for available dates: 10 minutes
EXCEPTION_TIME = 60*30  # wait time when an exception occurs: 30 minutes
COOLDOWN_TIME = 60*60  # wait time when temporary banned (empty list): 60 minutes
REST_TIME = 60*5 # rest time
NAP_TIME = 10 # rest time shorter

DATE_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/days/{FACILITY_ID}.json?appointments[expedite]=false"
TIME_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/times/{FACILITY_ID}.json?date=%s&appointments[expedite]=false"
APPOINTMENT_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment"
INSTRUCTIONS_URL = f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv/schedule/{SCHEDULE_ID}/appointment/instructions"

MY_SCHEDULE_DATE = datetime.strptime("2024-11-11", "%Y-%m-%d")

def print_current_time():
    print(f"Current precise time ", datetime.now())

def send_notification(message):
    print(f"Sending notification: {message}")

    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    parameters = {
        'chat_id': CHATID,
        'text': message
    }
    return requests.post(url, parameters)

def get_driver():
    if LOCAL_USE:
        dr = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    else:
        dr = webdriver.Remote(command_executor=HUB_ADDRESS, options=webdriver.ChromeOptions())
    return dr

driver = get_driver()


def login():
    # Bypass reCAPTCHA
    driver.get(f"https://ais.usvisa-info.com/{COUNTRY_CODE}/niv")
    time.sleep(STEP_TIME)
    a = driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]')
    a.click()
    time.sleep(STEP_TIME)

    print("Login start...")
    href = driver.find_element(By.XPATH, '//*[@id="header"]/nav/div[2]/div[1]/ul/li[3]/a')
    href.click()
    time.sleep(STEP_TIME)
    Wait(driver, 60).until(EC.presence_of_element_located((By.NAME, "commit")))

    print("\tclick bounce")
    a = driver.find_element(By.XPATH, '//a[@class="down-arrow bounce"]')
    a.click()
    time.sleep(STEP_TIME)

    do_login_action()


def do_login_action():
    print("\tinput email")
    user = driver.find_element(By.ID, 'user_email')
    user.send_keys(USERNAME)
    time.sleep(random.randint(1, 3))

    print("\tinput pwd")
    pw = driver.find_element(By.ID, 'user_password')
    pw.send_keys(PASSWORD)
    time.sleep(random.randint(1, 3))

    print("\tclick privacy")
    box = driver.find_element(By.CLASS_NAME, 'icheckbox')
    box .click()
    time.sleep(random.randint(1, 3))

    print("\tcommit")
    btn = driver.find_element(By.NAME, 'commit')
    btn.click()
    time.sleep(random.randint(1, 3))


def get_date():
    driver.get(DATE_URL)
    if not is_logged_in():
        login()
        return get_date()
    else:
        content = driver.find_element(By.TAG_NAME, 'pre').text
        date = json.loads(content)
        return date


def get_time(date):
    time_url = TIME_URL % date
    driver.get(time_url)
    content = driver.find_element(By.TAG_NAME, 'pre').text
    data = json.loads(content)
    time = data.get("available_times")[-1]
    print(f"Got time successfully! {date} {time}")
    return time

def get_current(): # current scheduled date time 
    """! Not in a very proper way. To be modified in the future
    """
    global MY_SCHEDULE_DATE
    driver.get(INSTRUCTIONS_URL)
    datetimestring = driver.find_element(by=By.XPATH, value='/html/body/div[4]/main/div[4]/div[1]/div/div[2]/div/div/div[2]/div/div[1]/div/p').get_attribute('textContent')
    print(datetimestring)
    datetimestring = datetimestring[1:-1] # get rid of the two /n of the head and the tail
    datetimestring = ' '.join(datetimestring.split(', ')[:2]).strip()
    MY_SCHEDULE_DATE = datetime.strptime(datetimestring, "%d %B %Y")
    send_notification(f"My scheduled date: {MY_SCHEDULE_DATE}")
    return MY_SCHEDULE_DATE

def reschedule(date):
    print(f"Starting Reschedule ({date})")
    print(f"Current precise time ", datetime.now())

    time = get_time(date)
    driver.get(APPOINTMENT_URL)

    data = {
        "utf8": driver.find_element(by=By.NAME, value='utf8').get_attribute('value'),
        "authenticity_token": driver.find_element(by=By.NAME, value='authenticity_token').get_attribute('value'),
        "confirmed_limit_message": driver.find_element(by=By.NAME, value='confirmed_limit_message').get_attribute('value'),
        "use_consulate_appointment_capacity": driver.find_element(by=By.NAME, value='use_consulate_appointment_capacity').get_attribute('value'),
        "appointments[consulate_appointment][facility_id]": FACILITY_ID,
        "appointments[consulate_appointment][date]": date,
        "appointments[consulate_appointment][time]": time,
    }

    headers = {
        "User-Agent": driver.execute_script("return navigator.userAgent;"),
        "Referer": APPOINTMENT_URL,
        "Cookie": "_yatri_session=" + driver.get_cookie("_yatri_session")["value"]
    }

    r = requests.post(APPOINTMENT_URL, headers=headers, data=data)
    
    get_current()
    msg = f'After reschedule try, current date: {MY_SCHEDULE_DATE}'
    send_notification(msg)


def is_logged_in():
    content = driver.page_source
    if(content.find("error") != -1):
        return False
    return True


def refresh():    
    print("REFRESH")
    print_current_time()
    driver.get(INSTRUCTIONS_URL) # avoid calling query API too many times
    driver.refresh() # avoiding auto logout

def print_dates(dates):
    print("Available dates:")
    for d in dates:
        print("%s \t business_day: %s" % (d.get('date'), d.get('business_day')))
    print()


def get_available_date(dates):
    
    def is_earlier(date):
        new_date = datetime.strptime(date, "%Y-%m-%d")
        result = MY_SCHEDULE_DATE > new_date
        print(f'Is {MY_SCHEDULE_DATE} > {new_date} ?\t{result}')
        return result

    print("Checking for an earlier date:")
    for d in dates:
        date = d.get('date')
        if is_earlier(date):
            year, month, day = date.split('-')
            if(MY_CONDITION(year, month, day)):
                return date


def update_reschedule():
    
    print("RESCHEDULE")
    print_current_time()
    dates = get_date()[:2]
    print_dates(dates)
    date = get_available_date(dates)
    print()
    print(f"New date: {date}")
    if date:
        reschedule(date)


def wake_up_condition_blocked():
    """
        Only wake up before exact hours
    """
    now = datetime.now()
    minute = now.minute
    if minute % 60 >= 55: return True
    return False
    
def wake_up_condition_unblocked():
    """
        Only wake up before every 10 mins
    """
    now = datetime.now()
    minute = now.minute
    if minute % 10 >= 5: return True
    return False
    
def wake_up_condition_nap():
    """
        Only wake up before every 10 mins
    """
    now = datetime.now()
    minute = now.minute
    seconds= now.second
    if minute % 10 == 0: return True
    NAP_TIME = 60 - seconds
    return False

if __name__ == "__main__":
    
    print(f"Current precise time ", datetime.now())
    print(f"Logging...")
    login()
    get_current()
    send_notification("LOL")

    schedule.every(3.3).minutes.do(refresh)
    schedule.every().hour.at(":00").do(update_reschedule)
    schedule.every().hour.at(":10").do(update_reschedule)
    schedule.every().hour.at(":20").do(update_reschedule)
    schedule.every().hour.at(":30").do(update_reschedule)
    schedule.every().hour.at(":40").do(update_reschedule)
    schedule.every().hour.at(":50").do(update_reschedule)

    while True:
        try:
            schedule.run_pending()
            time.sleep(1)

        except:
            time.sleep(EXCEPTION_TIME)

    driver.close()
    pass

