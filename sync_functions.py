import logging
import os
import zipfile
import tempfile
import hashlib
import rmapi_shim as rmapi
import remarks
from pathlib import Path
from shutil import rmtree
from pyzotero import zotero
from webdav3.client import Client as wdClient
from time import sleep
from datetime import datetime


logger = logging.getLogger(__name__)

def sync_to_rm(item, zot, folders):
    temp_path = Path(tempfile.gettempdir())
    item_id = item["key"]
    attachments = zot.children(item_id)
    logger.info(f"Syncing {len(attachments)} to reMarkable")
    for entry in attachments:
        if "contentType" in entry["data"] and entry["data"]["contentType"] == "application/pdf":
            attachment_id = attachments[attachments.index(entry)]["key"]
            attachment_name = zot.item(attachment_id)["data"]["filename"]
            logger.info(f"Processing {attachment_name}...")

            # Get actual file and repack it in reMarkable's file format
            zot.dump(attachment_id, path=temp_path)
            file_name = temp_path / attachment_name
            if file_name:
                if rmapi.upload_file(file_name, f"/Zotero/{folders['unread']}"):
                    zot.add_tags(item, "synced")
                    os.remove(file_name)
                    logger.info(f"Uploaded {attachment_name} to reMarkable.")
                else:
                    logger.error(f"Failed to upload {attachment_name} to reMarkable.")
        else:
            logger.warning("Found attachment, but it's not a PDF, skipping...")


def sync_to_rm_webdav(item, zot, webdav, folders):
    temp_path = Path(tempfile.gettempdir())
    item_id = item["key"]
    attachments = zot.children(item_id)
    for entry in attachments:
        if "contentType" in entry["data"] and entry["data"]["contentType"] == "application/pdf":
            attachment_id = attachments[attachments.index(entry)]["key"]
            attachment_name = zot.item(attachment_id)["data"]["filename"]
            logger.info(f"Processing {attachment_name}...")

            # Get actual file from webdav, extract it and repack it in reMarkable's file format
            file_name = f"{attachment_id}.zip"
            file_path = Path(temp_path / file_name)
            unzip_path = Path(temp_path / f"{file_name}-unzipped")
            webdav.download_sync(remote_path=file_name, local_path=file_path)
            with zipfile.ZipFile(file_path) as zf:
                zf.extractall(unzip_path)
                zf.extractall(".")
            if (unzip_path / attachment_name ).is_file():
                uploader = rmapi.upload_file(str(unzip_path / attachment_name), f"/Zotero/{folders['unread']}")
            else:
                """ #TODO: Sometimes Zotero does not seem to rename attachments properly,
                    leading to reported file names diverging from the actual one.
                    To prevent this from stopping the whole program due to missing
                    file errors, skip that file. Probably it could be worked around better though."""
                logger.warning("PDF not found in downloaded file. Filename might be different. Try renaming file in Zotero, sync and try again.")
                break
            if uploader:
                zot.add_tags(item, "synced")
                file_path.unlink()
                rmtree(unzip_path)
                logger.info(f"Uploaded {attachment_name} to reMarkable.")
            else:
                logger.error(f"Failed to upload {attachment_name} to reMarkable.")
        else:
            logger.info("Found attachment, but it's not a PDF, skipping...")


def download_from_rm(entity, folder):
    temp_path = Path(tempfile.gettempdir())
    logger.info(f"Processing {entity}...")
    zip_name = f"{entity}.zip"
    file_path = temp_path / zip_name
    unzip_path = temp_path / f"{entity}-unzipped"
    download = rmapi.download_file(f"{folder}{entity}", str(temp_path))
    if download == 0:
        logger.info("File downloaded")
    else:
        logger.warning("Failed to download file")

    with zipfile.ZipFile(file_path, "r") as zf:
        zf.extractall(unzip_path)

    print("zip extracted")
    remarks.run_remarks(str(unzip_path), str(temp_path))
    print("remarks run")
    logging.info("PDF rendered")
    pdf = Path(temp_path / f"{entity} _remarks.pdf")
    pdf = pdf.rename(pdf.with_stem(f"{entity}"))
    pdf_name = pdf.name

    logging.info("PDF written")
    file_path.unlink()
    rmtree(unzip_path)

    print("download done")
    return pdf_name

def _match_variations(rm_name, zot_name):
    if rm_name == zot_name:
        return True
    if zot_name == f"(Annot) {rm_name}":
        return True
    if zot_name == f"{rm_name}.pdf":
        return True
    if zot_name == f"(Annot) {rm_name}.pdf":
        return True
    return False

def zotero_get_last_modified_time(pdf_name, zot):
    file_found = False
    most_recent_date = None
    for item in zot.items(tag="synced"):
        item_id = item["key"]
        for attachment in zot.children(item_id):
            if "filename" in attachment["data"] and _match_variations(pdf_name, attachment["data"]["filename"]):
                file_found = True
                if "dateModified" in attachment["data"]:
                    date_modified = datetime.fromisoformat(attachment["data"]["dateModified"])
                    if most_recent_date is None or date_modified > most_recent_date:
                        most_recent_date = date_modified
    if most_recent_date is not None:
        return most_recent_date
    if file_found:
        return False # File found, but no date modified
    return None

def zotero_upload(pdf_name, zot):
    temp_path = Path(tempfile.gettempdir())
    for item in zot.items(tag="synced"):
        item_id = item["key"]
        for attachment in zot.children(item_id):
            if "filename" in attachment["data"] and attachment["data"]["filename"] == pdf_name:
                #zot.delete_item(attachment)
                # Keeping the original seems to be the more sensible thing to do
                pdf_name = temp_path / pdf_name
                pdf_path = Path(pdf_name)
                new_pdf_path = pdf_path.with_stem(f"(Annot) {pdf_path.stem}")
                pdf_path.rename(new_pdf_path)
                print(f"new_pdf_path: `{new_pdf_path}")
                upload = zot.attachment_simple([str(new_pdf_path)], item_id)

                if upload["success"]:
                    logging.info(f"{pdf_path} uploaded to Zotero.")
                else:
                    logging.error(f"Upload of {pdf_path} failed...")
                return


def get_md5(pdf) -> None | str:
    if pdf.is_file():
        with open(pdf, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()


def get_mtime() -> str:
    return datetime.now().strftime('%s')


def fill_template(item_template, pdf_name):
    item_template["title"] = pdf_name.stem
    item_template["filename"] = pdf_name.name
    item_template["md5"] = get_md5(pdf_name)
    item_template["mtime"] = get_mtime()
    return item_template


def webdav_uploader(webdav, remote_path, local_path):
    for i in range(3):
        try:
            webdav.upload_sync(remote_path=remote_path, local_path=local_path)
        except:
            sleep(5)
        else:
            return True
    else:
        return False


def zotero_upload_webdav(pdf_name, zot, webdav):
    temp_path = Path(tempfile.gettempdir())
    item_template = zot.item_template("attachment", "imported_file")
    for item in zot.items(tag=["synced", "-read"]):
        item_id = item["key"]
        for attachment in zot.children(item_id):
            if "filename" in attachment["data"] and attachment["data"]["filename"] == pdf_name:
                pdf_name = temp_path / pdf_name
                new_pdf_name = pdf_name.with_stem(f"(Annot) {pdf_name.stem}")
                pdf_name.rename(new_pdf_name)
                pdf_name = new_pdf_name
                filled_item_template = fill_template(item_template, pdf_name)
                create_attachment = zot.create_items([filled_item_template], item_id)

                if create_attachment["success"]:
                    key = create_attachment["success"]["0"]
                else:
                    logging.info("Failed to create attachment, aborting...")
                    continue

                attachment_zip = temp_path / f"{key}.zip"
                with zipfile.ZipFile(attachment_zip, "w") as zf:
                    zf.write(pdf_name, arcname=pdf_name.name)
                remote_attachment_zip = attachment_zip.name

                attachment_upload = webdav_uploader(webdav, remote_attachment_zip, attachment_zip)
                if attachment_upload:
                    logging.info("Attachment upload successful, proceeding...")
                else:
                    logging.error("Failed uploading attachment, skipping...")
                    continue

                """For the file to be properly recognized in Zotero, a propfile needs to be
                uploaded to the same folder with the same ID. The content needs
                to match exactly Zotero's format."""
                propfile_content = f'<properties version="1"><mtime>{item_template["mtime"]}</mtime><hash>{item_template["md5"]}</hash></properties>'
                propfile = temp_path / f"{key}.prop"
                with open(propfile, "w") as pf:
                    pf.write(propfile_content)
                remote_propfile = f"{key}.prop"

                propfile_upload = webdav_uploader(webdav, remote_propfile, propfile)
                if propfile_upload:
                    logging.info("Propfile upload successful, proceeding...")
                else:
                    logging.error("Propfile upload failed, skipping...")
                    continue

                zot.add_tags(item, "read")
                logging.info(f"{pdf_name.name} uploaded to Zotero.")
                (temp_path / pdf_name).unlink()
                (temp_path / attachment_zip).unlink()
                (temp_path / propfile).unlink()
                return pdf_name


def get_sync_status(zot):
    read_list = []
    for item in zot.items(tag="read"):
        for attachment in zot.children(item["key"]):
            if "contentType" in attachment["data"] and attachment["data"]["contentType"] == "application/pdf":
                read_list.append(attachment["data"]["filename"])

    return read_list
