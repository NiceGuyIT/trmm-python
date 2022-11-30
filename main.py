# Parse Active Backup for Business log files
#   https://kb.synology.com/en-br/DSM/help/ActiveBackup/activebackup_business_activities?version=7
# Future enhancement might be to use the Synology API:
#   https://github.com/N4S4/synology-api
import datetime
import json
import re
import sys

import pyparsing
from pyparsing import Word, alphas, Suppress, Combine, nums, string, Optional, Regex, White


# PyParsing Documentation: https://pyparsing-docs.readthedocs.io/en/latest/
# Source: https://github.com/pyparsing/pyparsing/


class Parser(object):
    def __init__(self):
        # https://pyparsing-docs.readthedocs.io/en/latest/HowToUsePyparsing.html#usage-notes
        numbers = Word(nums)

        # timestamp: Mon DD HH:MM:SS
        month = Word(string.ascii_uppercase, string.ascii_lowercase, exact=3)
        day = numbers
        hour = Combine(numbers + ":" + numbers + ":" + numbers)
        timestamp = Combine(month + White() + day + White() + hour).setResultsName("timestamp")

        # priority
        level = Word(string.ascii_uppercase).setResultsName("priority")
        priority = Suppress("[") + level + Suppress("]")

        # method name
        method_name = Word(alphas + nums + "_" + "-" + ".").setResultsName("method_name")

        # method line number
        method_num = Suppress("(") + numbers.setResultsName("method_num") + Suppress(")") + Suppress(":")

        # message
        message = Regex(r'.*', flags=re.DOTALL).setResultsName("message")

        # Build pattern to parse a log entry.
        self.__pattern = timestamp + priority + method_name + method_num + message

        # Action with JSON payload
        action = Word(string.ascii_lowercase) + Word(string.ascii_lowercase)

        # JSON message
        json_str = Regex(r"(?P<prefix>[^{]*)(?P<json>{.*})(?P<suffix>.*)", flags=re.DOTALL)

        # Build a pattern to parse a message entry with JSON.
        # self.__json_pattern = action + json_str
        self.__json_pattern = json_str

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


def main():
    parser = Parser()

    if len(sys.argv) == 1:
        print("Usage:\n  $ python main.py ./sample.log")
        exit(1)

    log_path = sys.argv[1]

    # Use the correct encoding.
    # https://stackoverflow.com/questions/17912307/u-ufeff-in-python-string/17912811#17912811
    #   Note that EF BB BF is a UTF-8-encoded BOM. It is not required for UTF-8, but serves only as a
    #   signature (usually on Windows).
    lines = []
    with open(log_path, mode="r", encoding="utf-8-sig") as fh:
        escape = False
        for line in fh.readlines():
            if not re.search(r'^\w{3} \d+ [\d:]{8}', line):
                # Multiline log entry; append to last line
                # JSON cannot have control characters and instead of escaping newlines and such, stripe all whitespace.
                if re.search(r'}$', line.strip()):
                    escape = False

                # Escape double quotes and strip whitespace (newlines) that cause problems parsing the JSON.
                if escape:
                    lines[len(lines) - 1] += line.strip().replace('"', '\\"')
                else:
                    lines[len(lines) - 1] += line.strip()
            else:
                # New log entry
                if re.search(r'"{$', line.strip()):
                    escape = True
                # lines.append(line.strip().replace('"{', '"\{'))
                lines.append(line.strip())

    for line in lines:
        fields = parser.parse(line)
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

                    last_backup = datetime.datetime.fromtimestamp(fields["json"]["backup_result"]["last_success_time"])
                    print(fields["json"]["backup_result"]["last_backup_status"],
                          fields["json"]["backup_result"]["last_success_time"],
                          last_backup.strftime('%c'))

                    print("-----")


# Enter here...
if __name__ == '__main__':
    main()
