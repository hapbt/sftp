from PyQt5.QtWidgets import QTableView, QApplication, QWidget, QVBoxLayout, QLabel, QFileDialog, QMessageBox, QInputDialog, QMenu, QHeaderView, QProgressBar, QSizePolicy
from PyQt5.QtCore import pyqtSignal, QTimer, Qt, QEventLoop, QModelIndex
from PyQt5 import QtCore
from stat import S_ISDIR
import stat
import os
import sys
import tempfile
import subprocess
import time
from icecream import ic
from pathlib import Path

from sftp_creds import get_credentials, create_random_integer, set_credentials
from sftp_downloadworkerclass import create_response_queue, delete_response_queue, check_response_queue, add_sftp_job, QueueItem, queue

class Browser(QWidget):
    def __init__(self, title, session_id, parent=None):
        super().__init__(parent)  # Initialize the QWidget parent class
        ic()
        self.observers = []
        self.title = title
        self.model = None
        self.session_id = session_id
        self.user_choice = None
        self.init_global_creds()
        self.init_ui()

    def init_global_creds(self):
        ic()
        creds = get_credentials(self.session_id)
        try:
            self.init_hostname = creds.get('hostname')
        except Exception as e:
            ic(e)

        self.init_username = creds.get('username')
        self.init_password = creds.get('password')
        self.init_port = creds.get('port')

    # Define a signal for sending messages to the console
    message_signal = pyqtSignal(str)

    def init_ui(self):
        ic()
        self.layout = QVBoxLayout()
        self.label = QLabel(self.title)
        self.layout.addWidget(self.label)
        # Initialize and set the model for the table
        self.table = QTableView()

        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        # Enable sorting
        self.table.setSortingEnabled(True)

        # Connect signals and slots
        self.table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.table.doubleClicked.connect(self.double_click_handler)
        self.table.customContextMenuRequested.connect(self.context_menu_handler)
        # UI configuration
        self.table.setFocusPolicy(Qt.StrongFocus)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.sortByColumn(0, Qt.AscendingOrder)

        self.layout.addWidget(self.table)  # Correctly add the table to the layout
        # Add the table and status bar to the layout
        self.progressBar = QProgressBar()
        self.layout.addWidget(self.progressBar)

        # Set the main layout of the widget
        self.setLayout(self.layout)

    def get_files(self):
        self.model.get_files()

    def add_observer(self,observer):
        if observer not in self.observers:
            self.observers.append(observer)
            ic("Observer added:", observer)
        else:
            ic("Observer already exists:", observer)

    def remove_observer(self,observer):
        if observer in self.observers:
            self.observers.remove(observer)
            ic("Observer removed:", observer)

    def notify_observers(self):
            ic()
            for observer in self.observers:
                try:
                    observer.get_files()  # Notify the observer by calling its update method
                    ic("Observer notified:", observer)
                except AttributeError as ae:
                    ic("Observer", observer, "does not implement 'get_files' method.", ae)
                except Exception as e:
                    ic("An error occurred while notifying observer", observer, e)

    def get_normalized_remote_path(self, current_remote_directory, partial_remote_path=None):
        """
        Get a normalized remote path by joining the current remote directory with a partial path.
        If no partial path is provided, return the normalized current remote directory.
        
        Args:
            current_remote_directory (str): The base directory on the remote server.
            partial_remote_path (str, optional): The partial path to be appended.
            
        Returns:
            str: The normalized remote path with forward slashes and no trailing slash.
        """
        # Replace backslashes with forward slashes in the base directory
        current_remote_directory = current_remote_directory.replace("\\", "/")

        if partial_remote_path is not None:
            # Replace backslashes with forward slashes in the partial path
            partial_remote_path = partial_remote_path.replace("\\", "/")
            
            # Join paths and normalize
            remote_path = os.path.join(current_remote_directory, partial_remote_path)
            normalized_path = os.path.normpath(remote_path)
        else:
            # Normalize the current remote directory
            normalized_path = os.path.normpath(current_remote_directory)
        
        # Convert backslashes to forward slashes in the final path
        normalized_path = normalized_path.replace("\\", "/")
        
        # Remove the trailing slash if it's not the root '/'
        if normalized_path != '/':
            normalized_path = normalized_path.rstrip('/')
        
        return normalized_path

    def is_complete_path(self, path):
        """
        Determine if a path is a complete path or just a filename/directory name.
        
        Args:
            path (str): The filesystem path to check.
            
        Returns:
            bool: True if the path is a complete path, False if it's just a filename/directory name.
        """
        # Convert to a Path object for easier manipulation
        p = Path(path)
        
        # Check if it's an absolute path or starts with a '/' (Unix-like absolute path)
        if p.is_absolute() or path.startswith('/'):
            return True
        
        # Check if it has more than one part (indicating it's not just a simple name)
        if len(p.parts) > 1:
            return True
        
        # Check if it ends with a slash (indicating it's intended as a directory name)
        if path.endswith('/') or path.endswith('\\'):
            return False
        
        # It's likely just a name if none of the above conditions are met
        return False        

    def split_path(self, path):
        ic()
        # try to deal with windows backslashes
        if "\\" in path:
            # Use "\\" as the separator
            head, tail = path.rsplit("\\", 1)
        elif "/" in path:
            # Use "/" as the separator
            head, tail = path.rsplit("/", 1)
        else:
            # No "\\" or "/" found, assume the entire string is the head
            head, tail = path, ""

        return head, tail

    def sftp_mkdir(self, remote_path):
        ic()
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "mkdir", job_id )

        while queue.empty():
            self.non_blocking_sleep(100)

        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_mkdir() {error}")
            f = False
        else:
            # if its a success then we dont care about the response and the queue will be deleted
            f = True

        delete_response_queue(job_id)
        self.model.get_files()
        self.notify_observers()
        return f

    def sftp_rmdir(self, remote_path):
        ic()
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "rmdir", job_id )

        while queue.empty():
            self.non_blocking_sleep(100)
        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_rmdir() {error}")
            f = False
        else:
            f = True

        delete_response_queue(job_id)
        self.get_files()
        self.notify_observers()
        return f

    def sftp_remove(self, remote_path ):
        ic()
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "remove", job_id )

        while queue.empty():
            self.non_blocking_sleep(100)
        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_remove() {error}")
            f = False
        else:
            f = True

        delete_response_queue(job_id)
        self.get_files()
        self.notify_observers()
        return f

    def sftp_listdir(self, remote_path ):
        ic()
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "listdir", job_id )

        self.progressBar.setRange(0, 0)
        while queue.empty():
            self.non_blocking_sleep(100)  # Sleeps for 1000 milliseconds (1 second)
        response = queue.get_nowait()
        self.progressBar.setRange(0, 100)

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_listdir() {error}")
            f = False
        else:
            list = queue.get_nowait()
            f = True

        delete_response_queue(job_id)
        if f:
            return list
        else:
            return f

    def non_blocking_sleep(self, ms):
        # special sleep function that can be used by a background/foreground thread, without causing a hang

        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec_()

    def sftp_listdir_attr(self, remote_path ):
        creds = get_credentials(self.session_id)
        # get remote directory listing with attributes from the remote_path

        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "listdir_attr", job_id )

        while queue.empty():
            self.non_blocking_sleep(100)
        response = queue.get_nowait()

        if response == "error":
            error = queue.get_nowait()
            self.message_signal.emit(f"FileBrowser sftp_listdir_attr() {error}")
            f = False
        else:
            list = queue.get_nowait()
            f = True

        delete_response_queue(job_id)
        if f:
            return list
        else:
            return f

    def normalize_path(self, path):
        """
        Normalize the given path by collapsing redundant slashes and up-level references.
        
        Args:
            path (str): The filesystem path to normalize.
            
        Returns:
            str: The normalized path.
        """
        return os.path.normpath(path)

    def on_header_clicked(self, logicalIndex):
        # Check the current sort order and toggle it
        # not the best, should really be revised 
        order = Qt.DescendingOrder if self.table.horizontalHeader().sortIndicatorOrder() == Qt.AscendingOrder else Qt.AscendingOrder
        self.table.sortByColumn(logicalIndex, order)

    def is_remote_directory(self, partial_remote_path):
        ic()
        ic(partial_remote_path)

        is_directory = False
        
        try:
            # Retrieve credentials once
            creds = get_credentials(self.session_id)

            # Normalize the path
            if not self.is_complete_path(partial_remote_path):
                remote_path = self.get_normalized_remote_path(creds.get('current_remote_directory'), partial_remote_path)
            else:
                remote_path = self.get_normalized_remote_path(partial_remote_path)
            
        except Exception as e:
            self.message_signal.emit(f"Error in getting credentials or forming remote path: {e}")
            ic(e)
            return False

        ic()
        ic(remote_path)

        # Create job and response queue
        job_id = create_random_integer()
        queue = create_response_queue(job_id)
        
        try:
            add_sftp_job(
                remote_path, True,
                remote_path, True,
                creds.get('hostname'), creds.get('username'), creds.get('password'),
                creds.get('port'), "stat", job_id
            )

            # Wait for a response
            while queue.empty():
                self.non_blocking_sleep(100)
            
            response = queue.get_nowait()
            ic(response)

            if response == "error":
                error = queue.get_nowait()
                self.message_signal.emit(f"SFTP job error: {error}")
                ic(error)
                return False

            # Extract attributes correctly from response
            attributes = queue.get_nowait()
            if stat.S_ISDIR(attributes.st_mode):
                is_directory = True
            
            #if isinstance(response, dict) and 'attributes' in response:
            #    attributes = response['attributes']
            #elif hasattr(response, 'mode'):
            #    attributes = response
            #else:
            #    self.message_signal.emit("Invalid attributes in response.")
            #    ic("Invalid attributes")
            #    ic(attributes)
            #    return False
        
        except queue.Empty:
            self.message_signal.emit("Queue was empty unexpectedly.")
            is_directory = False
        except Exception as e:
            self.message_signal.emit(f"Unexpected error: {e}")
            ic(e)
            is_directory = False
        finally:
            delete_response_queue(job_id)
            ic(is_directory)
            return is_directory

    def is_remote_file(self, partial_remote_path):
        is_file = False
        ic()
        
        try:
            # Retrieve credentials once
            creds = get_credentials(self.session_id)

            # Normalize the path
            if not self.is_complete_path(partial_remote_path):
                remote_path = self.get_normalized_remote_path(creds.get('current_remote_directory'), partial_remote_path)
            else:
                remote_path = self.get_normalized_remote_path(partial_remote_path)
            
        except Exception as e:
            self.message_signal.emit(f"Error in getting credentials or forming remote path: {e}")
            ic(e)
            return False

        # Create job and response queue
        job_id = create_random_integer()
        queue = create_response_queue(job_id)
        
        try:
            add_sftp_job(remote_path, True, remote_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "stat", job_id)

            # Wait for a response
            while queue.empty():
                self.non_blocking_sleep(100)

            response = queue.get_nowait()
            ic(response)

            if response != "error":
                attributes = queue.get_nowait()
                ic(attributes)
                is_directory = S_ISDIR(attributes.st_mode)
                is_file = not is_directory
            else:
                error = queue.get_nowait()
                ic(error)
                is_file = False

        except FileNotFoundError:
            is_file = False

        except Exception as e:
            self.message_signal.emit(f"FileBrowser is_remote_file() {e}")
            is_file = False

        finally:
            ic(is_file)
            delete_response_queue(job_id)
            return is_file

    def waitjob(self, job_id, timeout=30):  # 30 seconds timeout
        # Initialize the progress bar
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)

        progress_value = 0
        start_time = time.time()
        try:
            while not check_response_queue(job_id):
                if time.time() - start_time > timeout:
                    raise TimeoutError("Job timed out")
                
                # Increment progress by 10%, up to 100%
                progress_value = min(progress_value + 10, 100)
                self.progressBar.setValue(progress_value)

                # Sleep and process events to keep UI responsive
                self.non_blocking_sleep(100)
                QApplication.processEvents()  # Process any pending GUI events

        except (TimeoutError, KeyboardInterrupt) as e:
            self.message_signal.emit(f"Job interrupted: {str(e)}")
            return False
        finally:
            # Reset the progress bar after completion or interruption
            self.progressBar.setValue(100)
            self.progressBar.setRange(0, 100)

        # Return True if the job completed successfully
        return True

    def focusInEvent(self, event):
        self.setStyleSheet("""
            QTableWidget {
            background-color: #ffffff; /* Set background color */
            color: white;  /* Text color */
            border: 1px solid #cccccc; /* Add a thin border */
            selection-background-color: #e0e0e0; /* Set background color for selected items */
            }
        """)
        self.label.repaint()  # Force a repaint

    def focusOutEvent(self, event):
        self.setStyleSheet("""
            QTableWidget {
            background-color: #777777; /* Set background color */
            color: gray;  /* Text color */
            border: 1px solid #999999; /* Add a thin border */
            selection-background-color: #909090; /* Set background color for selected items */
            }
        """)
        self.label.repaint()  # Force a repaint

    def prompt_and_create_directory(self):
        creds = get_credentials(self.session_id)

        # Prompt the user for a new directory name
        directory_name, ok = QInputDialog.getText(
            None,
            'Create New Directory',
            'Enter the name of the new directory:'
        )

        if ok and directory_name:
            directory_path = os.path.join(creds.get('current_local_directory'), directory_name)

            try:
                # Attempt to create the directory locally
                os.makedirs(directory_path)
                self.message_signal.emit(f"Directory '{directory_path}' created successfully.")

            except Exception as e:
                QMessageBox.critical(None, 'Error', f"Error creating directory: {e}")
                self.message_signal.emit(f"Error creating directory: {e}")

            finally:
                self.model.get_files()
                self.notify_observers()

    def change_directory_handler(self):
        selected_path, ok = QInputDialog.getText(self, 'Input Dialog', 'Enter directory name:')

        if not ok:
            return

        try:
            is_directory = os.path.isdir(selected_path)

            if is_directory:
                # Call the method to change the directory
                self.change_directory(selected_path)

        except Exception as e:
            # Append error message to the output_console
            self.message_signal.emit(f"change_directory_handler() {e}")

        finally:
            self.model.get_files()
            self.notify_observers()

    def change_directory(self, path ):
        # this is a function to change the current LOCAL working directory, it also uses this moment to refresh the local file list

        try:
            # Local file browser
            os.chdir(path)
            set_credentials(self.session_id, 'current_local_directory', os.getcwd() )
            self.model.get_files()
            self.notify_observers()
        except Exception as e:
            # Append error message to the output_console
            self.message_signal.emit(f"change_directory() {e}")

    def double_click_handler(self, index):
        creds = get_credentials(self.session_id)
        if index.isValid():
            # Always get the data from the first column (filename)
            filename_index = self.model.index(index.row(), 0)
            filename = self.model.data(filename_index, Qt.DisplayRole)

            # Remove the icon prefix if present
            filename = filename.split(' ', 1)[-1] if ' ' in filename else filename

        try:
            if filename == "..":
                head, _ = self.split_path(creds.get('current_local_directory'))
                new_path = head
            else:
                new_path = os.path.join(creds.get('current_local_directory'), filename)

            # Check if the item is a directory
            is_directory = os.path.isdir(new_path)

            if is_directory:
                # Change the current working directory
                self.change_directory(new_path)
            else:
                # Handle file upload/download
                if self.is_local_view:
                    # Upload the file to the remote server
                    remote_path, _ = QFileDialog.getSaveFileName(self, "Select Remote Location", filename)
                    if remote_path:
                        self.upload_download(new_path)
                else:
                    # Download the file from the remote server
                    local_path, _ = QFileDialog.getSaveFileName(self, "Select Local Location", filename)
                    if local_path:
                        self.upload_download(new_path)

    except Exception as e:
        self.message_signal.emit(f"double_click_handler() error: {e}")

    def context_menu_handler(self, point):
        # If point is not provided, use the center of the list widget
        if not point:
            point = self.file_list.rect().center()

        # Get the currently focused widget
        current_browser = self.focusWidget()
        if current_browser is not None:
            menu = QMenu(self)
            # Add actions to the menu
            remove_dir_action = menu.addAction("Remove Directory")
            change_dir_action = menu.addAction("Change Directory")
            upload_download_action = menu.addAction("Upload/Download")
            prompt_and_create_directory = menu.addAction("Create Directory")
            view_edit_action = menu.addAction("View/Edit")
            
            # Add the new Refresh action
            refresh_action = menu.addAction("Refresh")

            # Connect the actions to corresponding methods
            remove_dir_action.triggered.connect(self.remove_directory_with_prompt)
            change_dir_action.triggered.connect(self.change_directory_handler)
            upload_download_action.triggered.connect(self.upload_download)
            prompt_and_create_directory.triggered.connect(self.prompt_and_create_directory)
            view_edit_action.triggered.connect(self.view_edit_file)
            
            # Connect the new Refresh action
            refresh_action.triggered.connect(self.refresh_files)

            # Show the menu at the cursor position
            menu.exec_(current_browser.mapToGlobal(point))

    def upload_download(self):
        ic()
        creds = get_credentials(self.session_id)
        current_browser = self.focusWidget()
        if current_browser is not None and isinstance(current_browser, QTableView):
            indexes = current_browser.selectedIndexes()
            has_valid_item = False  # Track if any valid items were found
            for index in indexes:
                ic(index)
                filename = ""
                if isinstance(index, QModelIndex):
                    if index.isValid():
                        # Always get the data from the first column (filename)
                        filename_index = current_browser.model().index(index.row(), 0)
                        filename = current_browser.model().data(filename_index, Qt.DisplayRole)
                        # Remove the decorative icon prefix if present
                        filename = filename.split(' ', 1)[-1] if ' ' in filename else filename
                elif isinstance(index, str):
                    filename = index
                    # Remove the decorative icon prefix if present
                    filename = filename.split(' ', 1)[-1] if ' ' in filename else filename

                if filename:
                    # Construct the full path of the selected item
                    if not self.is_complete_path(filename):
                        selected_path = os.path.join(creds.get('current_local_directory'), filename)
                    else:
                        selected_path = self.normalize_path(filename)
                    try:
                        remote_entry_path = self.get_normalized_remote_path(creds.get('current_remote_directory'), filename)
                        if os.path.isdir(selected_path):
                            self.message_signal.emit(f"Uploading directory: {selected_path}")
                            self.upload_directory(selected_path, remote_entry_path)
                        else:
                            self.message_signal.emit(f"Uploading file: {selected_path}")
                            job_id = create_random_integer()
                            queue_item = QueueItem(os.path.basename(selected_path), job_id)
                            # queue_display.append(queue_item)
                            add_sftp_job(selected_path, False, remote_entry_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "upload", job_id)
                        has_valid_item = True  # Mark as valid item found
                    except Exception as e:
                        self.message_signal.emit(f"upload_download() encountered an error: {e}")
                else:
                    self.message_signal.emit("Invalid item or empty path.")

            if not has_valid_item:
                self.message_signal.emit("No valid items selected.")
        else:
            self.message_signal.emit("Current browser is not a valid QTableView.")

    def upload_directory(self, source_directory, destination_directory, always=0):
        self.always = always
        creds = get_credentials(self.session_id)

        try:
            remote_folder = destination_directory

            target_exists = self.sftp_exists(remote_folder)

            if target_exists and self.is_remote_directory(remote_folder) and not self.always:
                response = self.show_prompt_dialog(f"The folder {remote_folder} already exists. Do you want to continue uploading?", "Upload Confirmation")

                if response == QMessageBox.No:
                    # User chose not to continue
                    return
                elif response == QMessageBox.Yes:
                    # User chose to continue
                    pass  # Continue with the upload
                elif response == QMessageBox.YesToAll:
                    # User chose to always continue
                    self.always = 1
                else:
                    # User closed the dialog
                    return
            else:
                try:
                    success = self.sftp_mkdir(remote_folder) 
                    self.notify_observers()                    
                    if not success or self.always_continue_upload:
                        self.message_signal.emit(f"sftp_mkdir() error creating {remote_folder} but always_continue_upload is {self.always_continue_upload}")
                        return
                except Exception as e:
                    self.message_signal.emit(f"{e}")
                    pass

            local_contents = os.listdir(source_directory)

            for entry in local_contents:
                entry_path = os.path.join(source_directory, entry)
                remote_entry_path = self.get_normalized_remote_path(remote_folder, entry)

                job_id = create_random_integer()

                if os.path.isdir(entry_path):
                    queue_item = QueueItem( os.path.basename(entry_path), job_id )
                    self.sftp_mkdir(remote_entry_path)
                    self.get_files()
                    self.upload_directory(entry_path, remote_entry_path, self.always)
                else:
                    self.message_signal.emit(f"{entry_path}, {remote_entry_path}")

                    queue_item = QueueItem( os.path.basename(entry_path), job_id )

                    add_sftp_job(entry_path, False, remote_entry_path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "upload", job_id)

        except Exception as e:
            self.message_signal.emit(f"upload_directory() {e}")
        
        finally:
            self.notify_observers()

    def show_prompt_dialog(self, text, title):
        dialog = QMessageBox(self.parent())
        dialog.setWindowTitle(title)
        dialog.setText(text)
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.YesToAll)
        dialog.setDefaultButton(QMessageBox.Yes)

        return dialog.exec_()

    def view_edit_file(self):
        creds = get_credentials(self.session_id)
        current_browser = self.focusWidget()

        if current_browser is not None and isinstance(current_browser, QTableView):
            indexes = current_browser.selectedIndexes()
            if indexes:
                index = indexes[0]  # Get the first selected item
                selected_item_text = current_browser.model().data(index, Qt.DisplayRole)
                
                if self.is_remote_file(selected_item_text):
                    remote_path = self.get_normalized_remote_path(creds.get('current_remote_directory'), selected_item_text)
                    
                    # Create a temporary file
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(selected_item_text)[1]) as temp_file:
                        temp_path = temp_file.name
                    
                    # Download the file to the temporary location
                    job_id = create_random_integer()
                    queue = create_response_queue(job_id)
                    add_sftp_job(remote_path, True, temp_path, False, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "download", job_id)
                    
                    # Wait for the download to complete
                    if not self.waitjob(job_id):
                        self.message_signal.emit("File download was interrupted or timed out.")
                        return
                    
                    # Open the file with the default application
                    try:
                        if sys.platform.startswith('darwin'):  # macOS
                            subprocess.Popen(['open', temp_path])
                        elif sys.platform.startswith('win'):  # Windows
                            os.startfile(temp_path)
                        else:  # Linux and other Unix-like
                            subprocess.Popen(['xdg-open', temp_path])
                        self.message_signal.emit(f"Opened file: {selected_item_text}")
                    except Exception as e:
                        self.message_signal.emit(f"Error opening file: {str(e)}")
                    
                    # TODO: Implement a mechanism to upload the file back if it was modified
                    # This could involve monitoring the file for changes and prompting the user to upload
                    
                else:
                    self.message_signal.emit("Selected item is not a remote file.")
            else:
                self.message_signal.emit("No item selected.")
        else:
            self.message_signal.emit("Current browser is not a valid QTableView.")

    def sftp_exists(self, path):
        creds = get_credentials(self.session_id)
        job_id = create_random_integer()
        queue = create_response_queue(job_id)

        try:
            add_sftp_job(path, True, path, True, creds.get('hostname'), creds.get('username'), creds.get('password'), creds.get('port'), "stat", job_id )

            while queue.empty():
                self.non_blocking_sleep(100)
            response = queue.get_nowait()

            if response == "error":
                error = queue.get_nowait() # get error message
                self.message_signal.emit(f"sftp_exists() {error}")
                raise error
            else: # success means what it is it exists
                exist = True

        except Exception as e:
            self.message_signal.emit(f"sftp_exists() {e}")
            exist = False

        finally:
            delete_response_queue(job_id)
            return exist
        
    def refresh_files(self):
        if hasattr(self.model, 'invalidate_cache'):
            self.model.invalidate_cache()
        self.get_files()
        self.notify_observers()
