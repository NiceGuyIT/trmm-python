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
import pyparsing


class SynologyActiveBackupLogs(object):
    def __init__(self, after=datetime.timedelta(days=365)):
        # Log pattern
        # self.__log_filename_glob = "log.txt*"
        self.__log_filename_glob = "log-testing.txt*"

        # __re_timestamp is a regular expression to extract the timestamp from the beginning of the logs.
        self.__re_timestamp = re.compile(r'^(?P<month>\w{3}) (?P<day>\d+) (?P<time>[\d:]{8})')

        # __re_everything is a regular expression to match the rest of the log message
        self.__re_everything = re.compile(r'.*')

        # __re_json is a regular expression to match the JSON payload in the message, surrounded by words before and
        # after the JSON payload
        self.__re_json = re.compile(r'(?P<prefix>[^{]*)(?P<json>{.*})(?P<suffix>.*)')

        # __re_escape_check is a regular expression to check if a message contains something that looks like JSON.
        self.__re_escape_check = re.compile(r'{.*}')
        # __re_escape_start is a regular expression to check for the start of an unescaped string.
        # self.__re_escape_start = re.compile(r'"{$')
        self.__re_escape_start = re.compile(r'("{$|"{")')
        # __re_escape_end is a regular expression to check for the end of an unescaped string.
        self.__re_escape_end = re.compile(r'}$')

        # __now is a timestamp used to determine if the log entry is after "now". 1 minute are added for
        # processing time.
        self.__now = datetime.datetime.now() + datetime.timedelta(minutes=1)

        # __current_year is the current year and used to determine if the log entry is for this year or last year.
        # The logs do not contain the year.
        self.__current_year = self.__now.year

        # __after is a timestamp used to calculate if the log should be included in the search
        # Default: 1 year ago (365 days)
        # self.since = datetime.timedelta(days=-365)
        if after:
            self.__after = after

        # __lines is an array of the log entries in the log file, one log entry per "line".
        self.__lines = []

        # __lines_ts is the timestamp for the corresponding line. The numerical offset needs to be kept in sync with
        # the lines.
        self.__lines_ts = []

        # __events is an array of the log entries that match the search criteria.
        self.__events = []

        # https://pyparsing-docs.readthedocs.io/en/latest/HowToUsePyparsing.html#usage-notes
        # Alias to improve readability
        numbers = pyparsing.Word(pyparsing.nums)

        # Timestamp at the beginning of the log entry
        # Format: Mon DD HH:MM:SS
        month = pyparsing.Word(pyparsing.string.ascii_uppercase, pyparsing.string.ascii_lowercase, exact=3)
        day = numbers
        hour = pyparsing.Combine(numbers + ":" + numbers + ":" + numbers)
        timestamp = pyparsing.Combine(month + pyparsing.White() +
                                      day + pyparsing.White() +
                                      hour).setResultsName("timestamp")

        # Priority of the log entry
        # Format: [INFO]
        level = pyparsing.Word(pyparsing.string.ascii_uppercase).setResultsName("priority")
        priority = pyparsing.Suppress("[") + level + pyparsing.Suppress("]")

        # Method name from the calling program
        # Format: server-requester.cpp
        method_name = pyparsing.Word(pyparsing.alphas + pyparsing.nums + "_" + "-" + ".").setResultsName("method_name")

        # Method line number from the calling program
        # Format: (68):
        method_num = pyparsing.Suppress("(") + numbers.setResultsName("method_num") + pyparsing.Suppress("):")

        # Message that is logged
        # The format has no rhyme or reason. Some entries have JSON payloads. Some just have words. Some entries span
        # multiple lines. The method name and line number can be used to determine the format type, but the line
        # number may change in each release.
        message = pyparsing.Regex(self.__re_everything, flags=re.DOTALL).setResultsName("message")

        # Pattern to parse a log entry
        self.__pattern = timestamp + priority + method_name + method_num + message

        # Build a pattern to parse a message entry with JSON.
        # self.__json_pattern = action + json_str
        self.__json_pattern = pyparsing.Regex(self.__re_json, flags=re.DOTALL)

    #
    def parse(self, log=None, log_ts=None):
        """
        Parse will parse the log entry into its component parts.

        :param log: string
        :param log_ts: datetime.datetime
        :return: None if there was a ParseException. dict of the parsed log.
        """
        try:
            parsed = self.__pattern.parseString(log)
        except pyparsing.ParseException as err:
            print("Failed to parse log entry")
            print(log)
            print(err.explain(err, depth=5))
            return None

        payload = {
            "datetime": log_ts,
            "timestamp": parsed["timestamp"],
            "priority": parsed["priority"],
            "method_name": parsed["method_name"],
            "method_num": parsed["method_num"],
            "message": parsed["message"],
            "json_str": None,
            "json": None,
        }

        # If the message has what looks like JSON, extract it from the payload.
        if re.search(self.__re_escape_check, payload["message"]):
            try:
                parsed_json = self.__json_pattern.parseString(payload["message"])
                if json not in parsed_json:
                    # print("Payload did not contain any JSON:")
                    # print(payload["message"])
                    # print(parsed_json)
                    return payload

                payload["json_str"] = parsed_json["json"].strip("'\n")
                # print("Parsing JSON:", payload["json_str"])
                try:
                    payload["json"] = json.loads(payload["json_str"], strict=False)
                    # print("JSON Object:", payload["json"])
                except json.decoder.JSONDecodeError as err:
                    print("ERR: Failed to parse JSON from message")
                    print("Input JSON string")
                    print(payload["json_str"])
                    print("Input log string")
                    print(payload["message"])
                    print("-----")
                    return payload

            except pyparsing.ParseException as err:
                print("ERR: Failed to parse log entry")
                print(log)
                print(err.explain(err, depth=5))
                return payload

        return payload

    def load_log_file(self, log_path):
        """
        log_log_file will iterate over the log files and load the log entries into an object.

        :param log_path: string
        :return: None
        """
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
                    ts = datetime.datetime.strptime("{year} {month} {day} {time}".format(
                        month=ts_match.group("month"),
                        day=ts_match.group("day"),
                        time=ts_match.group("time"),
                        year=self.__current_year,
                    ), "%Y %b %d %X")
                    if self.__now < ts:
                        # Log timestamp is in the future indicating the log entry is from last year. Subtract one year.
                        # FIXME: This does not take into account leap years. It may be off 1 day on leap years.
                        ts = ts - datetime.timedelta(days=365)

                    if self.__now - self.__after < ts:
                        # Log timestamp is after the "after" timestamp. Include it.
                        if re.search(self.__re_escape_start, line.strip()):
                            escape = True

                        # The current line might need to be escaped.
                        if escape:
                            # self.__lines.append(line.strip())
                            # self.__lines.append(line.strip().replace('"', '\\"'))
                            self.__lines.append(line.strip().replace('"{"', '"{\\"'))
                        else:
                            self.__lines.append(line.strip())

                        # Always include the timestamp
                        self.__lines_ts.append(ts)

                else:
                    # Multiline log entry; append to last line
                    # Log timestamp was before the "after" window and nothing is captured yet.
                    if len(self.__lines) == 0:
                        continue

                    # JSON cannot have control characters and instead of escaping newlines and such, stripe all
                    # whitespace.
                    if re.search(self.__re_escape_end, line.strip()):
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

        files = glob.glob(os.path.join(path, self.__log_filename_glob))
        files.sort(key=os.path.getmtime)
        for file in files:
            if datetime.datetime.fromtimestamp(os.path.getmtime(file)) > datetime.datetime.now() - self.__after:
                print("Processing log file:", file)
                self.load_log_file(file)

        return None

    # search will iterate over the log entries searching for lines "after" the window that match the values in find.
    # find is required.
    # Depth is limited by the code. ObjectPath can query objects and nested structures.
    # See https://stackoverflow.com/a/41496646
    def search(self, find):
        for x in range(len(self.__lines)):
            fields = self.parse(log=self.__lines[x], log_ts=self.__lines_ts[x])
            if fields and self.is_subset(find, fields):
                self.__events.append(fields)
        return self.__events

    # is_subset will recursively compare two dictionaries and return true if subset is a subset of the superset.
    def is_subset(self, subset, superset):
        if subset is None or superset is None:
            return False

        if isinstance(subset, dict):
            return all(key in superset and self.is_subset(val, superset[key]) for key, val in subset.items())

        if isinstance(subset, list) or isinstance(subset, set):
            return all(any(self.is_subset(subitem, superitem) for superitem in superset) for subitem in subset)

        # assume that subset is a plain value if none of the above match
        return subset == superset
