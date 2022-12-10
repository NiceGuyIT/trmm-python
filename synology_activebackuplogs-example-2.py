# This example will return all events with backup_results in the JSON.
import datetime
import sys
# TRMM snippet for production
# {{synology_activebackuplogs_snippet.py}}
# Dev
import synology_activebackuplogs_snippet


def main():
    # timedelta docs: https://docs.python.org/3/library/datetime.html#timedelta-objects
    # Note: "years" is not valid. Use "days=365" to represent one year.
    # Values include:
    #   weeks
    #   days
    #   hours
    #   minutes
    #   seconds
    after = datetime.timedelta(days=30)

    logs = synology_activebackuplogs_snippet.SynologyActiveBackupLogs(
        # Search logs within the period specified.
        # timedelta() will be off by 1 minute because 1 minute is added to detect if the log entry is last year vs.
        # this year. This should be negligible.
        after=after,

        # Use different log location
        log_path="logs",

        # Use different filename globbing
        # filename_glob="log.txt*",
    )

    # Load the log entries
    logs.load()

    # Search for entries that match the criteria.
    find = {
        "method_name": "server-requester.cpp",
        "json": {
            "backup_result": {
                # Find all records with backup_results
            }
        },
    }
    found = logs.search(find=find)
    if not found:
        # The timestamp above is not
        ts = (datetime.datetime.now() - after).strftime("%Y-%m-%d %X")
        print(f"No log entries found since {ts}")
        return

    # Check for errors
    errors_found = False

    # Print the log events
    for event in found:
        # Need to check if the keys are in the event. An error is thrown if a key is accessed that does not exist.
        if "last_success_time" not in event["json"]["backup_result"] or\
                "last_backup_status" not in event["json"]["backup_result"]:
            continue

        # Nicely formatted timestamp
        ts = event["datetime"].strftime("%Y-%m-%d %X")
        ts_backup = datetime.datetime.fromtimestamp(event["json"]["backup_result"]["last_success_time"])
        delta_backup = datetime.datetime.now() - ts_backup
        # delta_backup.days is an integer and does not take into account hours.
        if event["json"]["backup_result"]["last_backup_status"] == "complete" and delta_backup.days >= 3:
            errors_found = True

        # Always print the output so it's visible to the users.
        task_name = ""
        transfered = 0
        if "running_task_result" in event["json"]:
            if "task_name" in event["json"]['running_task_result']:
                task_name = event['json']['running_task_result']['task_name']
            if "transfered_bytes" in event["json"]['running_task_result']:
                transfered = event['json']['running_task_result']['transfered_bytes']

        print(f"{ts}: {event['json']['backup_result']}    Task name: {task_name}    Transfered: {transfered}    Days/Hours ago: {delta_backup}")
        #print(event)

    if errors_found:
        # Errors found. Exit with failure
        exit(1)
    else:
        # No errors found. Exit successful
        exit(0)


# Main entrance here...
if __name__ == '__main__':
    main()
