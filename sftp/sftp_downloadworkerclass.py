from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QListWidget, QTextEdit, QProgressBar, QSizePolicy
from PyQt5.QtCore import QThreadPool, QRunnable, QTimer

class DownloadWorker(QRunnable):
    def __init__(self, transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command=None):
        super(DownloadWorker, self).__init__()
        self.transfer_id = transfer_id
        self._stop_flag = False
        self.signals = WorkerSignals()
        self.ssh = paramiko.SSHClient()
        self.is_source_remote = is_source_remote
        self.job_source = job_source
        self.job_destination = job_destination
        self.is_destination_remote = is_destination_remote
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.command = command

    def convert_unit(self, size_in_bytes: int, unit: SIZE_UNIT):
        # """Convert the size from bytes to
        # other units like KB, MB or GB
        # """
        if unit == SIZE_UNIT.KB:
            return size_in_bytes/1024
        elif unit == SIZE_UNIT.MB:
            return size_in_bytes/(1024*1024)
        elif unit == SIZE_UNIT.GB:
            return size_in_bytes/(1024*1024*1024)
        else:
            return size_in_bytes

    def progress(self, transferred: int, tobe_transferred: int):
        # """Return progress every 50 MB"""
        if self._stop_flag:
            raise Exception("Transfer interrupted")
        percentage = round((float(transferred) / float(tobe_transferred)) * 100)
        self.signals.progress.emit(self.transfer_id,percentage)

    def run(self):
        try:
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(self.hostname, self.port, self.username, self.password)
            self.sftp = self.ssh.open_sftp()
        except Exception as e:
            self.signals.message.emit(self.transfer_id,f"download_thread() {e}")
            return

        if self.is_source_remote and not self.is_destination_remote:
            # Download from remote to local
            self.signals.message.emit(self.transfer_id,f"download_thread() {self.job_source},{self.job_destination}")
            try:
                self.sftp.get(self.job_source, self.job_destination, callback=self.progress)
            except:
                self.signals.message.emit(self.transfer_id,f"Transfer {self.transfer_id} was interrupted.")

            self.signals.finished.emit(self.transfer_id)

        elif self.is_destination_remote and not self.is_source_remote :
            # Upload from local to remote
            self.signals.message.emit(self.transfer_id,f"download_thread() {self.job_source},{self.job_destination}")
            try:
                self.sftp.put(self.job_source, self.job_destination, callback=self.progress)
            except:
                self.signals.message.emit(self.transfer_id,f"Transfer {self.transfer_id} was interrupted.")

        elif self.is_source_remote and self.is_destination_remote:
            # must be a mkdir
            try:
                if self.command == "mkdir":
                    try:
                        self.sftp.mkdir(self.job_destination)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_destination)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "listdir_attr":
                    try:
                        response = self.sftp.listdir_attr(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(response)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "listdir":
                    try:
                        response = self.sftp.listdir(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(response)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "chdir":
                    try:
                        self.sftp.chdir(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_source)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "rmdir":
                    try:
                        self.sftp.rmdir(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_source)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "stat":
                    try:
                        attr = self.sftp.stat(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(attr)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "remove":
                    try:
                        self.sftp.remove(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_source)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "getcwd":
                    try:
                        stdin, stdout, stderr = self.ssh.exec_command('cd {}'.format(self.job_source))
                        stdin, stdout, stderr = self.ssh.exec_command('pwd')
                        if stderr.read():
                            ic("Error:", stderr.read().decode())
                        getcwd_path = stdout.read().strip().decode()
                        # .replace("\\", "/")
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(getcwd_path)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

            except Exception as e:
                self.signals.message.emit(self.transfer_id, f"{self.command} operation failed: {e}")
                response_queues[self.transfer_id].put("error")
                response_queues[self.transfer_id].put(e)

            finally:
                self.sftp.close()
                self.ssh.close()

        self.signals.finished.emit(self.transfer_id)

    def stop_transfer(self):
        self._stop_flag = True
        self.signals.message.emit(self.transfer_id, f"Transfer {self.transfer_id} ends.")

class BackgroundThreadWindow(QMainWindow):
    def __init__(self):
        super(BackgroundThreadWindow, self).__init__()
        self.active_transfers = 0
        self.transfers = []
        self.init_ui()

    def init_ui(self):
        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        size_policy.setHorizontalStretch(1)
        size_policy.setVerticalStretch(1)

        self.layout = QVBoxLayout()

        self.list_widget = QListWidget()
        self.layout.addWidget(self.list_widget)

        self.text_console = QTextEdit()
        self.text_console.setReadOnly(True)  # Make the text console read-only
        self.text_console.setSizePolicy(size_policy)
        self.text_console.textChanged.connect(self.scroll_to_bottom)
        self.layout.addWidget(self.text_console)

        central_widget = QWidget()
        central_widget.setLayout(self.layout)
        self.setCentralWidget(central_widget)

        self.thread_pool = QThreadPool.globalInstance()
        # Setup a QTimer to periodically check the queue
        self.check_queue_timer = QTimer(self)
        self.check_queue_timer.timeout.connect(self.check_and_start_transfers)
        self.check_queue_timer.start(100)  # Check every 1000 ms (1 second)

    def remove_queue_item_by_id(self, id_to_remove):
        global queue_display

        # Iterate over the queue_display list and remove the item with the matching ID
        queue_display = [item for item in queue_display if item.id != id_to_remove]

        # Optionally, update the list widget after removal
        self.populate_queue_list()

    def populate_queue_list(self):
        global queue_display

        # Clear the list widget first
        self.list_widget.clear()

        # Iterate over the queue_display and add each filename to the list widget
        for item in queue_display:
            self.list_widget.addItem(item.name)

    def scroll_to_bottom(self):
        # Scroll to the bottom of the QTextEdit
        vertical_scroll_bar = self.text_console.verticalScrollBar()
        vertical_scroll_bar.setValue(vertical_scroll_bar.maximum())

    def check_and_start_transfers(self):
        global sftp_queue  # sftp_queue is a global variable

        # Check if more transfers can be started
        if sftp_queue.empty() or self.active_transfers == MAX_TRANSFERS:
            return
        else:
            job = sftp_queue.get_nowait()  # Wait for 5 seconds for a job

        self.populate_queue_list()

        if job.command == "end":
            self._stop_flag = 1
        else:
            hostname = job.hostname
            password = job.password
            port = job.port
            username = job.username
            command = job.command
            # response_queue = job.response_queue

            self.start_transfer(job.id, job.source_path, job.destination_path, job.is_source_remote, job.is_destination_remote, hostname, port, username, password, command )

    def start_transfer(self, transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command):
        # Create a horizontal layout for the progress bar and cancel button
        hbox = QHBoxLayout()

        # Create the textbox
        textbox = QLineEdit()
        textbox.setReadOnly(True)  # Make it read-only if needed
        textbox.setText(os.path.basename(job_source))  # Set text if needed
        hbox.addWidget(textbox, 2)  # Add it to the layout with a stretch factor

        # Create the progress bar
        progress_bar = QProgressBar()
        hbox.addWidget(progress_bar, 3)  # Add it to the layout with a stretch factor of 3

        # Create the cancel button
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(lambda: self.transfer_finished(transfer_id))
        hbox.addWidget(cancel_button, 1)  # Add it to the layout with a stretch factor of 1

        # Add the horizontal layout to the main layout
        self.layout.addLayout(hbox)

        # Store references to the widgets for later use
        new_transfer = Transfer(transfer_id=transfer_id, download_worker=DownloadWorker(transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command), active=True, hbox=hbox, progress_bar=progress_bar, cancel_button=cancel_button, tbox=textbox)

        # Create and configure the download worker
        new_transfer.download_worker.signals.progress.connect(lambda tid, val: self.update_progress(tid, val))
        new_transfer.download_worker.signals.finished.connect(lambda tid: self.transfer_finished(tid))
        new_transfer.download_worker.signals.message.connect(lambda tid, msg: self.update_text_console(tid, msg))

        self.transfers.append(new_transfer)
        # Start the download worker in the thread pool
        self.thread_pool.start(new_transfer.download_worker)
        self.active_transfers += 1

    def transfer_finished(self, transfer_id):
        # Find the transfer
        transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)

        if transfer is None:
            self.text_console.append(f"No transfer found with ID {transfer_id}")
            return

        # Deactivate the transfer
        transfer.active = False

        # Stop the download worker if it's active
        # if transfer.download_worker and not transfer.download_worker.isFinished():
        transfer.download_worker.stop_transfer()

        if transfer.tbox:
            transfer.tbox.deleteLater()
            transfer.tbox = None

        # Remove and delete the progress bar
        if transfer.progress_bar:
            transfer.progress_bar.deleteLater()
            transfer.progress_bar = None

        # Remove and delete the cancel button
        if transfer.cancel_button:
            transfer.cancel_button.deleteLater()
            transfer.cancel_button = None

        if transfer.hbox:  # Assuming each transfer has a reference to its QHBoxLayout
            # Find the index of the layout in the main layout and remove it
            index = self.layout.indexOf(transfer.hbox)
            if index != -1:
                layout_item = self.layout.takeAt(index)
                if layout_item:
                    widget = layout_item.widget()
                    if widget:
                        widget.deleteLater()

        # Remove the transfer from the list
        self.transfers = [t for t in self.transfers if t.transfer_id != transfer_id]
        self.text_console.append("Transfer removed from the transfers list.")
        self.remove_queue_item_by_id(transfer_id)
        self.active_transfers -= 1

    def update_text_console(self, transfer_id, message):
        if message:
            self.text_console.append(f"{message}")

    def update_progress(self, transfer_id, value):
        # Find the transfer with the given transfer_id
        transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)

        if transfer and transfer.progress_bar:
            # Update the progress bar's value
            transfer.progress_bar.setValue(value)
        else:
            self.text_console.append(f"update_progress() No active transfer found with ID {transfer_id}")