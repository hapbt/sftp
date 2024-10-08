from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QListWidget, QTextEdit, QProgressBar, QSizePolicy, QLabel
from PyQt5.QtCore import QThreadPool, QTimer, Qt
from icecream import ic
import os

from sftp_downloadworkerclass import Transfer, DownloadWorker, sftp_queue_get, sftp_queue_isempty

MAX_TRANSFERS = 4

class BackgroundThreadWindow(QMainWindow):
    def __init__(self):
        super(BackgroundThreadWindow, self).__init__()
        self.queue_items = []
        self.active_transfers = 0
        self.transfers = []
        self.observees = []
        self.total_queue_items = 0
        self.init_ui()
        
        # Set a fixed size for the window
        self.setFixedSize(400, 500)  # Adjust width and height as needed

    def init_ui(self):
        size_policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        size_policy.setHorizontalStretch(1)
        size_policy.setVerticalStretch(1)

        self.layout = QVBoxLayout()

        # Add overall queue progress bar
        self.overall_progress_layout = QHBoxLayout()
        self.overall_progress_label = QLabel("Overall Queue Progress:")
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setRange(0, 100)
        self.overall_progress_bar.setValue(0)
        self.overall_progress_layout.addWidget(self.overall_progress_label)
        self.overall_progress_layout.addWidget(self.overall_progress_bar)
        self.layout.addLayout(self.overall_progress_layout)

        self.list_widget = QListWidget()
        self.list_widget.setMaximumHeight(200)  # Set maximum height
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)  # Always show vertical scrollbar
        self.layout.addWidget(self.list_widget)

        self.text_console = QTextEdit()
        self.text_console.setReadOnly(True)  # Make the text console read-only
        self.text_console.setMaximumHeight(200)  # Set maximum height
        self.text_console.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)  # Always show vertical scrollbar
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
        self.check_queue_timer.start(100)  # Check every 100 ms

    def add_queue_item(self, item):
        if item not in self.queue_items:
            self.queue_items.append(item)
            self.total_queue_items += 1
            self.update_overall_progress()
            self.list_widget.addItem(item)

    def remove_queue_item(self, item):
        if item in self.queue_items:
            self.queue_items.remove(item)
            self.total_queue_items -= 1
            self.update_overall_progress()
            items = self.list_widget.findItems(item, Qt.MatchExactly)
            for list_item in items:
                self.list_widget.takeItem(self.list_widget.row(list_item))

    def add_observee(self, observee):
        if observee not in self.observees:
            self.observees.append(observee)
            ic("Observee added:", observee)
        else:
            ic("Observee already exists:", observee)

    def remove_observee(self, observee):
        if observee in self.observees:
            self.observees.remove(observee)
            ic("Observer removed:", observee)

    def notify_observees(self):
        ic()
        for observee in self.observees:
            try:
                observee.get_files()  # Notify the observer by calling its update method
                ic("Observee notified:", observee)
            except AttributeError as ae:
                ic("Observee", observee, "does not implement 'get_files' method.", ae)
            except Exception as e:
                ic("An error occurred while notifying observee", observee, e)

    def update_overall_progress(self):
        if self.total_queue_items > 0:
            progress = int((self.active_transfers / self.total_queue_items) * 100)
        else:
            progress = 0
        self.overall_progress_bar.setValue(progress)

    def scroll_to_bottom(self):
        # Scroll to the bottom of the QTextEdit
        vertical_scroll_bar = self.text_console.verticalScrollBar()
        vertical_scroll_bar.setValue(vertical_scroll_bar.maximum())

    def check_and_start_transfers(self):
        # Check if more transfers can be started
        if sftp_queue_isempty() or self.active_transfers == MAX_TRANSFERS:
            return
        else:
            job = sftp_queue_get()
            if job is None:
                return

        if job.command == "end":
            ic("end command given")
        else:
            hostname = job.hostname
            password = job.password
            port = job.port
            username = job.username
            command = job.command

            self.start_transfer(job.id, job.source_path, job.destination_path, job.is_source_remote, job.is_destination_remote, hostname, port, username, password, command)

    def start_transfer(self, transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command):
        # Create a vertical layout for the text and progress bar/cancel button
        vbox = QVBoxLayout()

        # Create the textbox
        textbox = QLineEdit()
        textbox.setReadOnly(True)
        
        # Set text with ellipsis if it's too long
        full_text = os.path.basename(job_source)
        max_length = 30  # Adjust this value as needed
        if len(full_text) > max_length:
            abbreviated_text = full_text[:max_length-3] + '...'
            textbox.setText(abbreviated_text)
            textbox.setToolTip(full_text)  # Show full text on hover
        else:
            textbox.setText(full_text)
        
        vbox.addWidget(textbox)

        # Create a horizontal layout for the progress bar and cancel button
        hbox = QHBoxLayout()

        # Create the progress bar
        progress_bar = QProgressBar()
        hbox.addWidget(progress_bar, 3)  # Add it to the layout with a stretch factor of 3

        # Create the cancel button
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(lambda: self.transfer_finished(transfer_id))
        hbox.addWidget(cancel_button, 1)  # Add it to the layout with a stretch factor of 1

        # Add the horizontal layout to the vertical layout
        vbox.addLayout(hbox)

        # Add the vertical layout to the main layout
        self.layout.addLayout(vbox)

        # Store references to the widgets for later use
        new_transfer = Transfer(transfer_id=transfer_id, download_worker=DownloadWorker(transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command), active=True, hbox=hbox, progress_bar=progress_bar, cancel_button=cancel_button, tbox=textbox)
        new_transfer.layout = vbox

        # Create and configure the download worker
        new_transfer.download_worker.signals.progress.connect(lambda tid, val: self.update_progress(tid, val))
        new_transfer.download_worker.signals.finished.connect(lambda tid: self.transfer_finished(tid))
        new_transfer.download_worker.signals.message.connect(lambda tid, msg: self.update_text_console(tid, msg))
        self.transfers.append(new_transfer)

        # Start the download worker in the thread pool
        self.thread_pool.start(new_transfer.download_worker)
        self.add_queue_item(job_source)
        self.active_transfers += 1
        self.update_overall_progress()

    def transfer_finished(self, transfer_id):
        # Find the transfer
        transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)

        if transfer is None:
            self.text_console.append(f"No transfer found with ID {transfer_id}")
            return

        # Deactivate the transfer
        transfer.active = False

        # Stop the download worker
        transfer.download_worker.stop_transfer()

        if transfer.tbox:
            transfer.tbox.deleteLater()
            transfer.tbox = None

        if transfer.progress_bar:
            transfer.progress_bar.deleteLater()
            transfer.progress_bar = None

        if transfer.cancel_button:
            transfer.cancel_button.deleteLater()
            transfer.cancel_button = None

        if transfer.layout:
            # Remove the layout from the main layout
            self.layout.removeItem(transfer.layout)
            # Delete all widgets in the layout
            while transfer.layout.count():
                item = transfer.layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()
            # Delete the layout itself
            transfer.layout.deleteLater()

        # Remove the transfer from the list
        self.transfers = [t for t in self.transfers if t.transfer_id != transfer_id]
        self.text_console.append("Transfer removed from the transfers list.")
        
        self.remove_queue_item(transfer.download_worker.job_source)
        self.active_transfers -= 1
        self.update_overall_progress()
        
        if transfer.download_worker.command == "upload" or transfer.download_worker.command == "download":
            self.notify_observees()

    def update_text_console(self, transfer_id, message):
        ic()
        if message:
            self.text_console.append(f"{message}")

    def update_progress(self, transfer_id, value):
        ic()
        # Find the transfer with the given transfer_id
        transfer = next((t for t in self.transfers if t.transfer_id == transfer_id), None)

        if transfer and transfer.progress_bar:
            # Update the progress bar's value
            transfer.progress_bar.setValue(value)
        else:
            self.text_console.append(f"update_progress() No active transfer found with ID {transfer_id}")