#
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
import logging
import time

from api.db.db_models import close_connection
from api.db.services.task_service import TaskService


def collect():
    doc_locations = TaskService.get_ongoing_doc_name()
    logging.debug(doc_locations)
    if len(doc_locations) == 0:
        time.sleep(1)
        return None
    return doc_locations


def main():
    # Redis file caching removed: task_executor reads directly from object
    # storage via settings.STORAGE_IMPL.get(), so pre-caching files in Redis
    # was redundant (no consumer ever read from the cache).
    locations = collect()
    if not locations:
        return
    logging.info(f"TASKS: {len(locations)}")


if __name__ == "__main__":
    while True:
        main()
        close_connection()
        time.sleep(1)
