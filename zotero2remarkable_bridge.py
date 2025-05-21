#!/usr/bin/python3
import logging
import sys
import getopt
from tqdm import tqdm
from config_functions import *
from sync_functions import *

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())
logger.addHandler(logging.FileHandler(filename="sync.log"))

def push(zot, webdav, folders):
    sync_items = zot.items(tag="to_sync")
    if sync_items:
        logger.info(f"Found {len(sync_items)} PDF attachments on the zotero to sync...")
        for item in tqdm(sync_items):
            if webdav:
                sync_to_rm_webdav(item, zot, webdav, folders)
            else:
                sync_to_rm(item, zot, folders)
    else:
        logger.info("No PDF attachments to sync, all clear :)")
    zot.delete_tags("to_sync")


def pull(zot, webdav, read_folder):
    files_list = rmapi.get_files(read_folder)
    if files_list:
        for entity in tqdm(files_list):
            metadata = rmapi.get_metadata(f"{read_folder}/{entity}")
            if metadata is not False:
                modified_time = datetime.fromisoformat(metadata["ModifiedClient"])
                zotero_last_modified_time = zotero_get_last_modified_time(entity, zot)
                if zotero_last_modified_time is not None:
                    if zotero_last_modified_time is False:
                        logger.info("No Zotero last modified time found, downloading anyway...")
                    elif modified_time > zotero_last_modified_time:
                        logger.info(f"File {entity} is newer on reMarkable, downloading...")
                    else:
                        logger.info(f"File {entity} is newer on Zotero, skipping...")
                        continue
                else:
                    logger.info(f"File {entity} not found in Zotero, skipping...")
            else:
                logger.info("Metadata not found, downloading anyway for safety...")
            pdf_name = download_from_rm(entity, read_folder)
            if webdav:
                zotero_upload_webdav(pdf_name, zot, webdav)
            else:
                zotero_upload(pdf_name, zot)
    else:
        logger.info("No files to pull found")


def main(argv):
    config_path = Path.cwd() / "config.yml"
    if config_path.exists():
        zot, webdav, folders = load_config("config.yml")
    else:
        write_config("config.yml")
        zot, webdav, folders = load_config("config.yml")
    read_folder = f"/Zotero/{folders['read']}/"

    try:
        opts, args = getopt.getopt(argv, "m:")
    except getopt.GetoptError:
        logger.error("No argument recognized")
        sys.exit()

    try:
        for opt, arg in opts:
            if opt == "-m":
                if arg == "push":
                    # Only sync files from Zotero to reMarkable
                    logger.info("Pushing...")
                    push(zot, webdav, folders)

                elif arg == "pull":
                    # Only get files from ReMarkable and upload to Zotero
                    logger.info("Pulling...")
                    pull(zot, webdav, read_folder)

                elif arg == "both":
                    # Do both
                    logger.info("Do both...")
                    # Upload...
                    push(zot, webdav, folders)

                    # ...and download, add highlighting and sync to Zotero.

                    pull(zot, webdav, read_folder)

                else:
                    logger.error("Invalid argument")
                    sys.exit()
    except Exception as e:
        logger.error(e)


main(sys.argv[1:])
