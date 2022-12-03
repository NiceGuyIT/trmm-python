# Parse Active Backup for Business log files
#   https://kb.synology.com/en-br/DSM/help/ActiveBackup/activebackup_business_activities?version=7
# Future enhancement might be to use the Synology API:
#   https://github.com/N4S4/synology-api
#
# PyParsing Documentation: https://pyparsing-docs.readthedocs.io/en/latest/
# Source: https://github.com/pyparsing/pyparsing/
import datetime
import glob
import json
import os.path
import re
import sys
import time

import pyparsing
from pyparsing import Word, alphas, Suppress, Combine, nums, string, Optional, Regex, White


class SynologyActiveBackupLogs(object):
    def __init__(self, after=datetime.timedelta(days=365)):
        # Regular expression to extract the timestamp from the beginning of the logs.
        self.__re_timestamp = re.compile(r'^(?P<month>\w{3}) (?P<day>\d+) (?P<time>[\d:]{8})')
        # Regular expression to match the rest of the log message
        self.__re_everything = re.compile(r'.*')
        # Regular expression to match the JSON payload in the message, surrounded by words before and after the JSON
        # payload
        self.__re_json = re.compile(r'(?P<prefix>[^{]*)(?P<json>{.*})(?P<suffix>.*)')

        # Timestamp used to determine if the log entry is after "now". Add 30 seconds for processing time.
        self.__now = datetime.datetime.now() + datetime.timedelta(seconds=30)

        # Current year is used to determine if the log entry is for this year or last year. The logs do not contain the
        # year.
        self.__current_year = self.__now.year

        # Timestamp used in calculating if the log should be searched
        # Default: 1 year ago (365 days)
        # self.since = datetime.timedelta(days=-365)
        if after:
            self.__after = after

        # Lines is an array of the log entries in the log file, one log entry per "line".
        self.__lines = []

        # Events is an array of the log entries that match the search criteria.
        self.events = []

        # https://pyparsing-docs.readthedocs.io/en/latest/HowToUsePyparsing.html#usage-notes
        # Alias to improve readability
        numbers = Word(nums)

        # Timestamp at the beginning of the log entry
        # Format: Mon DD HH:MM:SS
        month = Word(string.ascii_uppercase, string.ascii_lowercase, exact=3)
        day = numbers
        hour = Combine(numbers + ":" + numbers + ":" + numbers)
        timestamp = Combine(month + White() + day + White() + hour).setResultsName("timestamp")

        # Priority of the log entry
        # Format: [INFO]
        level = Word(string.ascii_uppercase).setResultsName("priority")
        priority = Suppress("[") + level + Suppress("]")

        # Method name from the calling program
        # Format: server-requester.cpp
        method_name = Word(alphas + nums + "_" + "-" + ".").setResultsName("method_name")

        # Method line number from the calling program
        # Format: (68):
        method_num = Suppress("(") + numbers.setResultsName("method_num") + Suppress(")") + Suppress(":")

        # Message that is logged
        # The format has no rhyme or reason. Some entries have JSON payloads. Some just have words. Some entries span
        # multiple lines. The method name and line number can be used to determine the format type, but the line
        # number may change in each release.
        message = Regex(self.__re_everything, flags=re.DOTALL).setResultsName("message")

        # Pattern to parse a log entry
        self.__pattern = timestamp + priority + method_name + method_num + message

        # Action with JSON payload, usually "send request" or "recv response"
        # action = Word(string.ascii_lowercase) + Word(string.ascii_lowercase)

        # JSON message
        json_str = Regex(self.__re_json, flags=re.DOTALL)

        # Build a pattern to parse a message entry with JSON.
        # self.__json_pattern = action + json_str
        self.__json_pattern = json_str

    # Parse will parse the log entry into its component parts.
    def parse(self, log):
        try:
            parsed = self.__pattern.parseString(log)
        except pyparsing.ParseException as err:
            print("Failed to parse log entry")
            print(log)
            print(err.explain(err, depth=5))
            return None

        payload = {
            # "timestamp": strftime("%Y-%m-%d %H:%M:%S"),
            # "timestamp": datetime.datetime(2022, parsed[0], parsed[1], ...),
            # "timestamp": parsed[0] + " " + parsed[1] + " " + parsed[2],
            "timestamp": parsed["timestamp"],
            "priority": parsed["priority"],
            "method_name": parsed["method_name"],
            "method_num": parsed["method_num"],
            "message": parsed["message"],
            "json_str": None,
            "json": None,
        }
        # If the message is an API call, extract the JSON from the payload
        # if re.search(r'^send request|recv response|get response', payload["message"]):
        if re.search(r"{.*}", payload["message"]):
            try:
                parsed_json = self.__json_pattern.parseString(payload["message"])
                payload["json_str"] = parsed_json["json"].strip("'\n")
                # print("Parsing JSON:", payload["json_str"])
                try:
                    payload["json"] = json.loads(payload["json_str"], strict=False)
                    # print("JSON Object:", payload["json"])
                except json.decoder.JSONDecodeError as err:
                    print("ERR: Failed to parse JSON from message")
                    print(payload["json_str"])
                    print(err)
                    return payload

            except pyparsing.ParseException as err:
                print("ERR: Failed to parse log entry")
                print(log)
                print(err.explain(err, depth=5))
                return payload
        # else:
        #     print("Not JSON:", payload["message"])

        return payload

    # log_log_file will iterate over the logs files and load the log entries into an object
    def load_log_file(self, log_path):
        # Use the correct encoding.
        # https://stackoverflow.com/questions/17912307/u-ufeff-in-python-string/17912811#17912811
        #   Note that EF BB BF is a UTF-8-encoded BOM. It is not required for UTF-8, but serves only as a
        #   signature (usually on Windows).
        with open(log_path, mode="r", encoding="utf-8-sig") as fh:
            escape = False
            for line in fh.readlines():
                ts_match = self.__re_timestamp.match(line)
                if ts_match:
                    # New log entry
                    # Check if the timestamp is before the threshold
                    ts = datetime.datetime.strptime('{year} {month} {day} {time}'.format(
                        month=ts_match.group('month'),
                        day=ts_match.group('day'),
                        time=ts_match.group('time'),
                        year=self.__current_year,
                        ), "%Y %b %d %X")
                    if self.__now < ts:
                        # Log timestamp is in the future indicating the log entry is from last year. Subtract one year.
                        # FIXME: This does not take into account leap years. It may be off 1 day on leap years.
                        ts = ts - datetime.timedelta(days=365)

                    if self.__now - self.__after < ts:
                        # Log timestamp is after the "after" timestamp. Include it.
                        # print("Including log entry:", ts.strftime("%F %T"))
                        if re.search(r'"{$', line.strip()):
                            escape = True
                        self.__lines.append(line.strip())

                else:
                    # Multiline log entry; append to last line
                    # Log timestamp was before the "after" window and nothing is captured yet.
                    if len(self.__lines) == 0:
                        continue

                    # JSON cannot have control characters and instead of escaping newlines and such, stripe all
                    # whitespace.
                    if re.search(r'}$', line.strip()):
                        escape = False

                    # Escape double quotes and strip whitespace (newlines) that cause problems parsing the JSON.
                    if escape:
                        self.__lines[len(self.__lines) - 1] += line.strip().replace('"', '\\"')
                    else:
                        self.__lines[len(self.__lines) - 1] += line.strip()

    # load will load all the log files in the path.
    def load(self, path=None):
        if not os.path.isdir(path):
            print("Error: Log directory does not exist: {dir}".format(dir=path))
            return None

        files = glob.glob(os.path.join(path, "log.txt*"))
        files.sort(key=os.path.getmtime)
        for file in files:
            if datetime.datetime.fromtimestamp(os.path.getmtime(file)) > datetime.datetime.now() - self.__after:
                print("Processing log file:", file)
                self.load_log_file(file)

        return None

    # search will iterate over the log entries searching for lines "since" the timestamp.
    def search(self):
        for line in self.__lines:
            fields = self.parse(line)
            if fields:
                # print(fields)
                if "json" in fields and fields["json"]:
                    # print("Line:", line)
                    # print("Fields:", fields)
                    # print("JSON:", fields["json"])
                    # print(fields["json"])
                    if "backup_result" in fields["json"]:
                        if "last_backup_status" not in fields["json"]["backup_result"]:
                            print("last_backup_status not found in backup_result:", fields["json"]["backup_result"])
                            continue

                        if "last_success_time" not in fields["json"]["backup_result"]:
                            print("last_success_time not found in backup_result:", fields["json"]["backup_result"])
                            continue

                        last_backup = datetime.datetime.fromtimestamp(
                            fields["json"]["backup_result"]["last_success_time"])
                        print("last_backup_status: {last_backup_status} last_success_time: {last_success_time} last_backup_strftime: {last_backup_strftime}".format(
                            last_backup_status=fields["json"]["backup_result"]["last_backup_status"],
                            last_success_time=fields["json"]["backup_result"]["last_success_time"],
                            last_backup_strftime=last_backup.strftime('%c'),
                        ))

                        print("-----")

        return None


# Main method
def main():
    if len(sys.argv) == 1:
        print("Usage:\n  $ python synology_active_backup_logs.py ./sample.log")
        exit(1)

    # timedelta docs: https://docs.python.org/3/library/datetime.html#timedelta-objects
    # Note: "years" is not valid. Use "days=365" to represent one year.
    # timedelta() will be off by 30 seconds because 30 seconds is added to detect if the log entry is last year vs.
    # this year. This should be negligible.
    logs = SynologyActiveBackupLogs(after=datetime.timedelta(days=8))
    logs.load(path=sys.argv[1])
    logs.search()


# Enter here...
if __name__ == '__main__':
    main()
