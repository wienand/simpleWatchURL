import argparse
import datetime
import difflib
import logging
import os
import pickle
import re
import time

# Only needed for sending email via EWS API
import requests
import urllib3.exceptions

# Only one connection to EWS
account = None
# We will later ignore certificate validation and hence disable the warnings here
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Remove the following artefacts from the response prior to comparison
artefacts = [
    #    re.compile(r"<!-- page generated from wsccms-php\d*-prod -->", re.IGNORECASE),
    re.compile(r'<img class="o-stage__image".*?>', re.IGNORECASE)
]


def send_smtp(subject, message, from_address, to_recipients, bcc_recipients, smtp_server, smtp_port, smtp_username,
              smtp_password):
    import smtplib

    server = smtplib.SMTP(smtp_server, smtp_port)
    server.ehlo()
    server.starttls()
    server.login(smtp_username, smtp_password)
    server.sendmail(from_address, to_recipients + bcc_recipients, message)
    server.close()
    logging.debug('Send message %s to %s (bcc: %s).', subject, to_recipients, bcc_recipients)


def send_email(subject, body, from_address=None, to_recipients=None, bcc_recipients=None,
               smtp_server=None, smtp_port=587, smtp_username=None, smtp_password=None, **_):
    if smtp_server is None:
        return

    # Prepare actual message
    message = """From: %s\nTo: %s\nSubject: %s\n\n%s
    """ % (from_address, ", ".join(to_recipients), subject, body)
    # noinspection PyBroadException
    try:
        message = message.encode('utf8')
        send_smtp(subject, message, from_address, to_recipients, bcc_recipients,
                  smtp_server, smtp_port, smtp_username, smtp_password)
    except:
        logging.exception('Could not send mail (%s to %s (bcc: %s):\n%s',
                          subject, to_recipients, bcc_recipients, message)
        # noinspection PyBroadException
        try:
            # Prepare message without body
            message = """From: %s\nTo: %s\nSubject: %s\n\n%s
            """ % (from_address, ", ".join(to_recipients), subject, 'NO  BODY DUE TO ERROR')
            send_smtp(subject, message, from_address, to_recipients, bcc_recipients,
                      smtp_server, smtp_port, smtp_username, smtp_password)
        except:
            logging.exception('Could not send mail without body (%s to %s (bcc:%s))',
                              subject, to_recipients, bcc_recipients)


def send_email_ews(subject, body, to_recipients=None, bcc_recipients=None, ews_server=None,
                   ews_primary_smtp_address=None, ews_username=None, ews_password=None, **_):
    if ews_server is None:
        return

    import exchangelib
    global account
    if account is None:
        credentials = exchangelib.Credentials(username=ews_username, password=ews_password)
        config = exchangelib.Configuration(server=ews_server, credentials=credentials)
        account = exchangelib.Account(primary_smtp_address=ews_primary_smtp_address, config=config, autodiscover=False,
                                      access_type=exchangelib.DELEGATE)
    m = exchangelib.Message(
        account=account,
        folder=account.sent,
        subject=subject,
        body=body,
        to_recipients=to_recipients,
        bcc_recipients=bcc_recipients
    )
    m.send_and_save()


def notify_change(url_path, old_data, new_data, **kwargs):
    with open(datetime.datetime.now().strftime('old %Y-%m-%d %H_%M_%S_%f.txt'), 'w', encoding='utf8') as output:
        output.write(url_path)
        output.write(old_data)
    with open(datetime.datetime.now().strftime('new %Y-%m-%d %H_%M_%S_%f.txt'), 'w', encoding='utf8') as output:
        output.write(url_path)
        output.write(new_data)
    subject = 'Changed detected at: %s' % url_path
    body = subject + '\n\n' + '\n'.join(
        difflib.context_diff(old_data.splitlines(keepends=False), new_data.splitlines(keepends=False)))
    send_email_ews(subject, body, **kwargs)
    send_email(subject, body, **kwargs)


def remove_artefacts(data):
    for artefact in artefacts:
        data = artefact.sub('', data)
    return data


def simple_url_get(url):
    return requests.get(url, verify=False)


def get_bew(bew_url):
    return requests.post(bew_url,
                         data="{\"from\":\"2022-11-14\",\"to\":\"2022-11-20\",\"mode\":\"Week_single\",\"date\":\"2022-11-14\",\"manager_id\":\"12578\",\"season_mode\":\"live\",\"widget\":\"true\",\"locations\":[\"13001\"],\"platform_widget_id\":\"424\"}",
                         verify=False)


def main(args):
    watched_urls = [[url, simple_url_get] for url in args.url]
    # Custom requests currently have to be hard coded
    # watched_urls.append(["https://booking.locaboo.com/calendar/load_events", get_bew])
    logging.debug('Watching URLs for changes: %s', [url for url, _ in watched_urls])
    if os.path.exists('old_data.pickle'):
        logging.info('Using stored snapshots for urls ...')
        old_data = pickle.load(open('old_data.pickle', 'rb'))
    else:
        logging.info('Generating snapshots for urls NOW ...')
        old_data = {url: retrieve(url).text for url, retrieve in watched_urls}
        pickle.dump(old_data, open('old_data.pickle', 'wb'))
        logging.debug('Snapshots stored.')
    while True:
        time.sleep(args.interval)
        for url, retrieve in watched_urls:
            logging.debug('Get current data from: %s', url)
            # noinspection PyBroadException
            try:
                result = retrieve(url)
                if result.status_code > 299:
                    logging.warning('Request not successful, skipping comparison this time: %s for %s',
                                    result.status_code, url)
                    continue
            except:
                logging.exception('Exception during requests for %s', url)
                continue
            new_data = result.text
            if remove_artefacts(old_data[url]) != remove_artefacts(new_data):
                logging.info('Difference detected for URL, sending notification (to: %s, bcc: %s): %s',
                             args.to_recipients, args.bcc_recipients, url)
                notify_change(url, old_data[url], new_data, **args.__dict__)
                old_data[url] = new_data
                pickle.dump(old_data, open('old_data.pickle', 'wb'))


def parse_command_line():
    parser = argparse.ArgumentParser(description='Alert on changes of URL')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-v', '--verbose', action='store_true', help='be very verbose')
    group.add_argument('-q', '--quiet', action='store_true', help='no logging except errors')
    parser.add_argument('--echo-ews', action='store_true', help='show debug from using EWS API')

    parser.add_argument('-u', '--url', action='append', required=False,
                        help='URL to monitor, e.g. https://www.random.org/integers/?num=100&min=1&max=100&col=5&base=10&format=html&rnd=new')
    parser.add_argument('-i', '--interval', default=30, type=int, help='seconds to wait prior to next diff')

    parser.add_argument('--from-address', help='sender email address')
    parser.add_argument('--to-recipients', action='append', help='email address to notify')
    parser.add_argument('--bcc-recipients', action='append', help='bcc email addresses to notify', default=[])

    parser.add_argument('--smtp-server', help='SMTP server name, will use TLS in any case')
    parser.add_argument('--smtp-port', type=int, default=587, help='SMTP server port')
    parser.add_argument('--smtp-username', help='SMTP username')
    parser.add_argument('--smtp-password', help='SMTP password')

    parser.add_argument('--ews-server', help='EWS server name')
    parser.add_argument('--ews-primary_smtp_address', help='EWS primary smtp address of mailbox')
    parser.add_argument('--ews-username', help='EWS username')
    parser.add_argument('--ews-password', help='EWS password')

    return parser.parse_args()


if __name__ == '__main__':
    startTimestamp = datetime.datetime.now()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(module)s %(levelname)s %(message)s')
    formatter = logging.Formatter('%(asctime)s %(module)s %(levelname)s %(message)s')
    fileHandler = logging.FileHandler('watch.log', mode='a')
    fileHandler.setFormatter(formatter)
    logging.getLogger().addHandler(fileHandler)
    arguments = parse_command_line()
    if not arguments.echo_ews:
        logging.getLogger('exchangelib').setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
    if arguments.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    if arguments.quiet:
        logging.getLogger().setLevel(logging.ERROR)
    main(arguments)
