import datetime
import sys
import synology_active_backup_logs_snippet as sab


# Main method
def main():
    if len(sys.argv) == 1:
        print("Usage:\n  $ python synology_activebackuplogs.py ./sample.log")
        exit(1)

    # See the payload declaration in synology_activebackuplogs_snippet.py
    # Example:
    # Nov 25 22:12:34 [INFO] async-worker.cpp (56): Worker (0): get event '1: routine {"subaction": "heart_beat"}', start processing
    # payload = {
    #     "timestamp": "Nov 25 22:12:34",
    #     "priority": "INFO",
    #     "method_name": "async-worker.cpp",
    #     "method_num": "56",
    #     "message": "Worker (0): get event '1: routine {"subaction": "heart_beat"}', start processing",
    #     "json_str": "{\"subaction\": \"heart_beat\"}",
    #     "json": {"subaction": "heart_beat"},
    # }
    # find = {
    #     'priority': 'ERROR',
    # }
    # find = {
    #     # 'method_name': 'win32-volume.cpp',
    #     'method_name': 'volume-info-manager-win-impl.cpp',
    # }
    find = {
        'method_name': 'async-worker.cpp',
        # 'json': {
        #     'backup_result': {
        #         # Find all records with backup_results
        #     }
        # },
    }

    # timedelta docs: https://docs.python.org/3/library/datetime.html#timedelta-objects
    # Note: "years" is not valid. Use "days=365" to represent one year.
    # timedelta() will be off by 30 seconds because 30 seconds is added to detect if the log entry is last year vs.
    # this year. This should be negligible.
    logs = sab.SynologyActiveBackupLogs(
        after=datetime.timedelta(days=18),
        log_path=sys.argv[1],
        # filename_glob="log-testing.txt*",
    )
    logs.load()
    found = logs.search(find=find)
    if not found:
        print("Did not find any log events")
        return

    # Print the log events
    for event in found:
        print(f"Event: {event['method_name']} {event['method_num']} {event['json']}")


# Enter here...
if __name__ == '__main__':
    main()
