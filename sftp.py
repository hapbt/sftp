import sys
import base64
import os
import argparse
import json
import platform
# import qdarktheme
import logging

from icecream import ic
ic.configureOutput(prefix='DEBUG | ')
ic.disable()
from PyQt5.QtWidgets import QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QCompleter, QComboBox, QSpinBox, QTabWidget, QMessageBox
from PyQt5.QtCore import pyqtSignal, QObject, QCoreApplication, Qt, QTimer
from cryptography.fernet import Fernet

# Configure logging
##logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
##logging.getLogger("paramiko").setLevel(logging.WARNING)

from sftp_downloadworkerclass import transferSignals, add_sftp_job, sftp_queue_clear
from PyQt5.QtCore import pyqtSignal
from sftp_backgroundthreadwindow import BackgroundThreadWindow
from sftp_editwindowclass import EditDialogContainer
from sftp_remotefilebrowserclass import RemoteFileBrowser
from sftp_filebrowserclass import FileBrowser
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit
from sftp_creds import get_credentials, set_credentials, del_credentials, create_random_integer

MAX_HOST_DATA_SIZE = 10  # Set your desired maximum size

class CustomComboBox(QComboBox):
    editingFinished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editingFinished.emit()

# Define SIZE_UNIT and WorkerSignals as necessary
MAX_TRANSFERS = 4

class WorkerSignals(QObject):
    error = pyqtSignal(int, str)

class MainWindow(QMainWindow):  # Inherits from QMainWindow
    def __init__(self):
        super().__init__()
        self.transfers_message = transferSignals()
        
        # Set up NSApplicationDelegate
        if sys.platform == 'darwin':
            try:
                from Foundation import NSObject
                from AppKit import NSApplication
                class AppDelegate(NSObject):
                    def applicationSupportsSecureRestorableState_(self, app):
                        return True
                    
                    def application_openURLs_(self, app, urls):
                        # Handle the URLs here
                        pass
                delegate = AppDelegate.alloc().init()
                NSApplication.sharedApplication().setDelegate_(delegate)
            except ImportError:
                print("Failed to import Foundation or AppKit. Secure coding for restorable state is not enabled.")
        # Custom data structure to store hostname, username, and password together
        self.create_initial_data()
        self.host_data = {
            "hostnames" : {},
            "usernames" : {},
            "passwords" : {},
            "ports" : {} }

        # Previous text to check for changes
        QCoreApplication.instance().aboutToQuit.connect(self.cleanup)
        self.hostnames = []
        self.sessions = []
        self.observers = []
        self._notifying = False  # Flag to track notification status
        self.output_console = QTextEdit()
        self.output_console.setReadOnly(True)

        # Create and connect to the error signal from WorkerSignals
        self.worker_signals = WorkerSignals()
        self.worker_signals.error.connect(self._display_error)

        # Load saved connection data and encryption key
        self.load_connection_data()

        # Initialize UI after loading connection data
        self.init_ui()

    def _display_error(self, transfer_id, message):
        # Display error in a message box
        QMessageBox.critical(self, "Error", f"Transfer {transfer_id}: {message}")
        
        # Display the error in the global output console
        self.global_output_console.append(f"Error in transfer {transfer_id}: {message}")
        
        # Display the error in the tab-specific console if it exists
        current_tab = self.tab_widget.currentWidget()
        if hasattr(current_tab, 'output_console'):
            current_tab.output_console.append(f"Error in transfer {transfer_id}: {message}")

    def init_ui(self):
        # Initialize input widgets
        self.container_layout = QVBoxLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.port_selector = QLineEdit()

        # Initialize buttons
        self.connect_button = QPushButton("Connect")
        self.edit_button = QPushButton("Edit Host Data")
        self.transfers_button = QPushButton("Show/Hide Transfers")
        self.clear_queue_button = QPushButton("Clear Queue")

        # Initialize hostname combo box
        self.hostname_combo = CustomComboBox(self)  # Pass self as parent
        self.hostname_combo.setEditable(True)
        self.populate_hostname_combo()  # New method to populate the combo box

        # Initialize spin box
        self.spinBox = QSpinBox()
        self.spinBox.setMinimum(2)
        self.spinBox.setMaximum(10)
        self.spinBox.setValue(4)
        self.spinBox.valueChanged.connect(self.on_value_changed)  # Ensure this slot is implemented

        # Initialize layouts
        self.init_top_bar_layout()
        self.init_button_layout()

        # Set main layout
        self.top_layout = QVBoxLayout()
        self.top_layout.addLayout(self.top_bar_layout)
        self.top_layout.addLayout(self.button_layout)

        # Set up central widget
        self.central_widget = QWidget()
        self.central_widget.setLayout(self.top_layout)
        self.setCentralWidget(self.central_widget)

        # Initialize tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.closeTab)

        # Additional setup if necessary
        self.setup_hostname_completer()

        # Add the tab widget to the top layout
        # Create global output console
        self.global_output_console = QTextEdit()
        self.global_output_console.setReadOnly(True)
        self.global_output_console.setMaximumHeight(150)  # Limit the height
        
        # Add the global output console to the layout
        self.top_layout.addWidget(self.global_output_console)
        
        # Add the tab widget below the global output console
        self.top_layout.addWidget(self.tab_widget)

    def init_top_bar_layout(self):
        self.top_bar_layout = QHBoxLayout()
        self.top_bar_layout.addWidget(self.hostname_combo, 3)
        self.top_bar_layout.addWidget(self.username, 3)
        self.top_bar_layout.addWidget(self.password, 3)
        self.top_bar_layout.addWidget(self.port_selector, 1)
        self.top_bar_layout.addWidget(self.spinBox)

        # Assuming self.connect_button_pressed is a method that handles the connection logic
        # Connect returnPressed signal of QLineEdit widgets to connect_button_pressed
        self.username.returnPressed.connect(self.connect_button_pressed)
        self.password.returnPressed.connect(self.connect_button_pressed)
        self.port_selector.returnPressed.connect(self.connect_button_pressed)

    def init_button_layout(self):
        self.button_layout = QHBoxLayout()
        self.button_layout.addWidget(self.connect_button)
        self.button_layout.addWidget(self.transfers_button)
        self.button_layout.addWidget(self.clear_queue_button)
        self.button_layout.addWidget(self.edit_button)

        # Connect the clicked signal of the edit button to the open_edit_dialog method
        self.edit_button.clicked.connect(self.open_edit_dialog)

        # Connect the clicked signal of the connect button to the connect_button_pressed method
        self.connect_button.clicked.connect(self.connect_button_pressed)

    def setup_hostname_completer(self):
        # Make sure self.hostnames is initialized and filled with data
        self.hostname_completer = QCompleter(self.hostnames)
        self.hostname_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.hostname_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.hostname_combo.setCompleter(self.hostname_completer)

        # Connect signals for hostname combo box
        self.hostname_combo.currentIndexChanged.connect(self.hostname_changed)  # Ensure this slot is implemented
        self.hostname_combo.activated.connect(self.hostname_changed)
        self.hostname_combo.editingFinished.connect(self.hostname_changed)        

    def populate_hostname_combo(self):
        # Clear existing items
        self.hostname_combo.clear()
        
        # Add hostnames from the host_data
        for hostname in self.host_data['hostnames'].keys():
            self.hostname_combo.addItem(hostname)
        
        # Update the hostnames list for the completer
        self.hostnames = list(self.host_data['hostnames'].keys())

    def prepare_container_widget(self):
        # Create a container widget
        container_widget = QWidget()

        # Create the browsers
        self.left_browser = FileBrowser("Local Files", self.session_id)
        self.right_browser = RemoteFileBrowser("Remote Files", self.session_id)

        # Create a layout for the browsers
        browser_layout = QHBoxLayout()
        
        browser_layout.addWidget(self.left_browser)
        browser_layout.addWidget(self.right_browser)

        self.left_browser.add_observer(self.right_browser)
        self.right_browser.add_observer(self.left_browser)
        self.backgroundThreadWindow.add_observee(self.right_browser)
        self.backgroundThreadWindow.add_observee(self.left_browser)

        # Create tab-specific output console
        tab_output_console = QTextEdit()
        tab_output_console.setReadOnly(True)
        tab_output_console.setMaximumHeight(100)  # Limit the height

        # Create the main layout
        main_layout = QVBoxLayout()
        main_layout.addLayout(browser_layout)
        main_layout.addWidget(tab_output_console)
        
        # Store the tab-specific console in the container widget
        container_widget.output_console = tab_output_console

        # Set the main layout to the container widget
        container_widget.setLayout(main_layout)
        self.log_connection_success()
            
        return container_widget

    def closeTab(self, index):
        # Close the tab at the given index
        widget_to_remove = self.tab_widget.widget(index)
        self.tab_widget.removeTab(index)

        # Close SFTP connection
        if hasattr(widget_to_remove, 'right_browser'):
            widget_to_remove.right_browser.close_sftp_connection()

        # Delete the widget if necessary
        widget_to_remove.deleteLater()
        self.backgroundThreadWindow.remove_observee(widget_to_remove.left_browser)
        self.backgroundThreadWindow.remove_observee(widget_to_remove.right_browser)

    def setup_left_browser(self, session_id):
        self.session_id = session_id
        # creds = get_credentials(self.session_id)
        set_credentials(self.session_id, 'current_local_directory', os.getcwd())

        try:
            self.left_browser = FileBrowser("Local Files", self.session_id)
            self.left_browser.table.setFocusPolicy(Qt.StrongFocus)
            self.left_browser.message_signal.connect(self.update_console)
            self.container_layout.addWidget(self.left_browser)

        except Exception as e:
            print(f"Error setting up left browser: {e}")
            pass

    def setup_right_browser(self, session_id):
        self.session_id = session_id
        try:
            self.right_browser = RemoteFileBrowser(title=self.title, session_id=self.session_id)
            self.right_browser.table.setFocusPolicy(Qt.StrongFocus)
            self.right_browser.message_signal.connect(self.update_console)

        except Exception as e:
            pass

    def YouAddTab(self, session_id, widget):
        self.session_id = session_id

        # Assuming these methods are correctly defined and handle their tasks appropriately
        self.title = self.get_session_title(self.session_id)
        
        # print("call setup_left_browser")
        self.setup_left_browser( self.session_id )
        self.setup_right_browser( self.session_id )
        # Create tab-specific output console
        tab_output_console = QTextEdit()
        tab_output_console.setReadOnly(True)
        tab_output_console.setMaximumHeight(100)  # Limit the height

        # Prepare the container widget
        container_widget = self.prepare_container_widget()

        # Add widget to the tab widget with the title
        # Add the container widget as a new tab
        tab_title = self.get_session_title(session_id)  # Retrieves the title for the tab
        self.tab_widget.addTab(container_widget, tab_title)

        self.log_connection_success()  # Ensure this method is implemented

    def initialize_session_credentials(self, session_id):
        self.session_id = session_id

        self.title = self.get_session_title(self.session_id)
        self.tab_widget.addTab(self.tab_widget, self.title)
        self.sessions.append(self.tab_widget)

    def get_session_title(self, session_id):
        self.session_id = session_id
        creds = get_credentials(self.session_id)

        try:
            title = creds.get('hostname') if creds else "Unknown Hostname"
        except KeyError:
            title = "Unknown Hostname"
        return title

    def setup_output_console(self):
        # Initialize output console
        self.output_console = QTextEdit()
        self.output_console.setReadOnly(True)
        self.container_layout.addWidget(self.output_console)

    def log_connection_success(self):
        success_message = "Connected successfully"
        self.output_console.append(success_message)

    def hostname_changed(self):
        self.current_hostname = self.hostname_combo.currentText().strip()  # Strip whitespace

        # Access data from the nested dictionaries
        if self.current_hostname in self.host_data['hostnames']:
            username = self.host_data['usernames'].get(self.current_hostname, '')
            password = self.host_data['passwords'].get(self.current_hostname, '')
            port = self.host_data['ports'].get(self.current_hostname, '')

            self.username.setText(username)
            self.password.setText(password)
            self.port_selector.setText(str(port))  # Convert port to string
        else:
            # If the hostname is not in the history, clear the fields
            self.username.clear()
            self.password.clear()
            self.port_selector.clear()

        # Update the UI
        self.username.repaint()
        self.password.repaint()
        self.port_selector.repaint()

    def removeTab(self, session_id):
        creds = get_credentials(self.session_id)
        self.tabWidget.removeTab( self.tabs[session_id] )
        del self.tabs[session_id]  # Remove the reference from the list
        del_credentials(self.session_id)

    def on_value_changed(self, value):
        global MAX_TRANSFERS
        MAX_TRANSFERS = value

    def update_completer(self):
        # Update the list of hostnames
        self.hostnames = list(self.host_data['hostnames'].keys())  # Adjusted to fetch keys from the 'hostnames' dict within host_data

        # Clear and repopulate the hostname combo box
        self.hostname_combo.clear()
        self.hostname_combo.addItems(self.hostnames)

        # Reinitialize the completer with the updated list
        self.hostname_completer = QCompleter(self.hostnames)
        self.hostname_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.hostname_completer.setCompletionMode(QCompleter.PopupCompletion)
        self.hostname_combo.setCompleter(self.hostname_completer)

    def open_edit_dialog(self):
        # Initialize the container widget for the tab
        editDialogContainer = EditDialogContainer(self.host_data)
        editDialogContainer.editDialog.entryDoubleClicked.connect(self.onEntryDoubleClicked)
        editDialogContainer.editDialog.dataChanged.connect(self.onHostDataChanged)

        # Add the container as a new tab
        self.tab_widget.addTab(editDialogContainer, "Edit Host Data")

        # Set the newly added tab as the current tab
        self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)

    def onHostDataChanged(self, updated_data):
        self.host_data = updated_data
        self.save_connection_data()
        self.update_completer()

    def onEntryDoubleClicked(self, entry):
        hostname = entry.get("hostname", "localhost")
        username = entry.get("username", "guest")
        password = entry.get("password", "guest")
        port = entry.get("port", "22")

        self.connect(hostname=hostname, username=username, password=password, port=port)

    def closeEvent(self, event):
        # Assuming you have a reference to BackgroundThreadWindow instance
        if self.backgroundThreadWindow:
            self.backgroundThreadWindow.close()
        event.accept()  # Accept the close event

    # Function to safely clear a queue
    def clear_queue(self, q):
        try:
            while True:  # Continue until an Empty exception is raised
                q.get_nowait()  # Remove an item from the queue
                q.task_done()  # Indicate that a formerly enqueued task is complete
        except Exception as e:
            pass  # Queue is empty, break the loop

    def clear_queue_clicked(self):
        sftp_queue_clear()
        self.output_console.append("queue cleared")

    def transfers_button_clicked(self):
        self.transfers_message.showhide.emit()

    def update_console(self, message):
        # Update both the global and tab-specific consoles with the received message
        self.global_output_console.append(message)
        
        # Update the tab-specific console if it exists
        current_tab = self.tab_widget.currentWidget()
        if hasattr(current_tab, 'output_console'):
            current_tab.output_console.append(message)

    def connect_button_pressed(self):
        try:
            session_id = self.connect()
            if session_id is None:
                # Connection failed, error has already been displayed
                return
            # If needed, add any post-connection logic here
        except Exception as e:
            error_message = f"Connection failed: {str(e)}"
            self.display_error(error_message)
            self.update_console(error_message)

    def display_error(self, transfer_id, message):
        # Display error in a message box
        QMessageBox.critical(self, "Error", f"Transfer {transfer_id}: {message}")
        
        # Display the error in the global output console
        self.global_output_console.append(f"Error in transfer {transfer_id}: {message}")
        
        # Display the error in the tab-specific console if it exists
        current_tab = self.tab_widget.currentWidget()
        if hasattr(current_tab, 'output_console'):
            current_tab.output_console.append(f"Error in transfer {transfer_id}: {message}")

    def connect(self, hostname="localhost", username="guest", password="guest", port="22"):
        self.temp_hostname = self.hostname_combo.currentText() if hostname == "localhost" and self.hostname_combo.currentText() else hostname
        self.update_console(f"Connecting to {self.temp_hostname}...")
        QApplication.processEvents()  # Force GUI update
        
        try:
            self.session_id = create_random_integer()

            # Hostname, username, password, and port handling
            self.temp_hostname = self.hostname_combo.currentText() if hostname == "localhost" and self.hostname_combo.currentText() else hostname
            self.temp_username = self.username.text() if username == "guest" and self.username.text() else username
            self.temp_password = self.password.text() if password == "guest" and self.password.text() else password
            self.temp_port = self.port_selector.text() or port or "22"

            if not self.temp_hostname:
                raise ValueError("Hostname is required")
            if not self.temp_username:
                raise ValueError("Username is required")
            if not self.temp_password:
                raise ValueError("Password is required")
            try:
                self.temp_port = int(self.temp_port)  # Validate port is a number
            except ValueError:
                raise ValueError("Port must be a valid number")

            # Set credentials synchronously
            self.set_credentials_async()

            # Test the connection
            self.test_connection()

            # Create a new QWidget as a container for both the file table and the output console
            self.container_widget = self.prepare_container_widget()

            # Add tab synchronously
            self.YouAddTab(self.session_id, self.container_widget)

            self.update_console(f"Successfully connected to {self.temp_hostname}")

            # Save connection data synchronously
            self.save_connection_data_async()

            return self.session_id
        except ValueError as ve:
            error_message = str(ve)
            QMessageBox.critical(self, "Connection Error", error_message)
            self.update_console(f"Connection failed: {error_message}")
        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            QMessageBox.critical(self, "Connection Error", error_message)
            self.update_console(f"Connection failed: {error_message}")
        return None

    def test_connection(self):
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(self.temp_hostname, port=self.temp_port, username=self.temp_username, password=self.temp_password)
            ssh.close()
        except Exception as e:
            raise Exception(f"Failed to connect: {str(e)}")

    def set_credentials_async(self):
        set_credentials(self.session_id, 'hostname', self.temp_hostname)
        set_credentials(self.session_id, 'username', self.temp_username)
        set_credentials(self.session_id, 'password', self.temp_password)
        set_credentials(self.session_id, 'port', str(self.temp_port))
        set_credentials(self.session_id, 'current_local_directory', os.getcwd())
        set_credentials(self.session_id, 'current_remote_directory', '.')

    def save_connection_data_async(self):
        self.host_data["hostnames"][self.temp_hostname] = self.temp_hostname
        self.host_data["usernames"][self.temp_hostname] = self.temp_username
        self.host_data["passwords"][self.temp_hostname] = self.temp_password
        self.host_data["ports"][self.temp_hostname] = str(self.temp_port)
        self.save_connection_data()
        self.update_completer()

    def create_initial_data(self):
        """
        Create initial data for the application.
        This includes defining the data to be written to the JSON file.
        """
        # Example data for demonstration purposes
        self.host_data = {
            "localhost": {
                "username": "guest",
                "password": "WjNWbGMzUT0=",  # Note: This should be securely stored/encrypted
                "port": 22  # Port should be an integer
            }
        }
        
    def cleanup(self):
        try:
            # Close all open SFTP connections
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if hasattr(widget, 'right_browser'):
                    widget.right_browser.close_sftp_connection()
            
            # Clear the transfer queue
            sftp_queue_clear()
            
            # Signal the background thread to stop
            add_sftp_job(".", False, ".", False, "localhost", "guest", "guest", 69, "end", 69)

            # Save connection data before exiting
            self.save_connection_data()
        except Exception as e:
            print(f"Error during cleanup: {str(e)}")
        finally:
            # Set a timeout for the cleanup process
            QTimer.singleShot(5000, self.force_exit)

    def force_exit(self):
        print("Forcing application exit...")
        QCoreApplication.instance().quit()

    def closeEvent(self, event):
        QTimer.singleShot(0, self.cleanup)  # Start cleanup on next event loop iteration
        event.accept()

    def save_connection_data(self):
        data = {
            "hostnames": self.host_data["hostnames"],
            "usernames": self.host_data["usernames"],
            "passwords": {k: self.cipher_suite.encrypt(v.encode()).decode() for k, v in self.host_data["passwords"].items()},
            "ports": self.host_data["ports"],
            "encryption_key": self.encryption_key.decode()  # Save the encryption key
        }
        with open('connection_data.json', 'w') as f:
            json.dump(data, f)

    def load_connection_data(self):
        try:
            with open('connection_data.json', 'r') as f:
                data = json.load(f)
            
            # Load the encryption key first
            self.encryption_key = data.get("encryption_key", Fernet.generate_key()).encode()
            self.cipher_suite = Fernet(self.encryption_key)

            self.host_data["hostnames"] = data.get("hostnames", {})
            self.host_data["usernames"] = data.get("usernames", {})
            self.host_data["passwords"] = {k: self.cipher_suite.decrypt(v.encode()).decode() for k, v in data.get("passwords", {}).items()}
            self.host_data["ports"] = data.get("ports", {})
            self.hostnames = list(self.host_data["hostnames"].keys())
            
            # Only update the completer if hostname_combo exists
            if hasattr(self, 'hostname_combo'):
                self.update_completer()
        except FileNotFoundError:
            # If the file doesn't exist, generate a new encryption key and create an empty structure
            self.encryption_key = Fernet.generate_key()
            self.cipher_suite = Fernet(self.encryption_key)
            self.host_data = {"hostnames": {}, "usernames": {}, "passwords": {}, "ports": {}}
            self.hostnames = []
        except Exception as e:
            print(f"Error loading connection data: {str(e)}")
            # If there's any error, generate a new encryption key and create an empty structure
            self.encryption_key = Fernet.generate_key()
            self.cipher_suite = Fernet(self.encryption_key)
            self.host_data = {"hostnames": {}, "usernames": {}, "passwords": {}, "ports": {}}
            self.hostnames = []

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="FTP/SFTP Client")
    parser.add_argument("-H", "--hostname", help="Initial hostname to connect to")
    parser.add_argument("-u", "--username", help="Username for the connection")
    parser.add_argument("-p", "--password", help="Password for the connection")
    parser.add_argument("-P", "--port", type=int, default=22, help="Port for the connection (default: 22)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    if args.debug:
        ic.enable()
    else:
        ic.disable()

    def hide_transfers_window():
        if not hasattr(hide_transfers_window, "transfers_hidden"):
            hide_transfers_window.transfers_hidden = 1  # Initialize it once
            background_thread_window.hide()
        elif hide_transfers_window.transfers_hidden == 0:
            background_thread_window.hide()
            hide_transfers_window.transfers_hidden = 1
        elif hide_transfers_window.transfers_hidden == 1:
            background_thread_window.show()
            hide_transfers_window.transfers_hidden = 0

    app = QApplication(sys.argv)
    # app.setStyle('Fusion')
    # qdarktheme.setup_theme()

    # create the window we show the statuses of active transfers in, this is for downloads/uploads but also any background event like fetching a directory listing etc
    background_thread_window = BackgroundThreadWindow()
    background_thread_window.setWindowTitle("Transfer Queue")
    background_thread_window.show()

    # create the main window of the application
    main_window = MainWindow()
    main_window.setWindowTitle("FTP/SFTP Client")
    main_window.resize(800, 600)
    main_window.show()
    main_window.backgroundThreadWindow = background_thread_window
    main_window.transfers_message.showhide.connect(hide_transfers_window)

    # If command line arguments are provided, initiate the connection
    if args.hostname:
        try:
            main_window.connect(
                hostname=args.hostname,
                username=args.username or "guest",
                password=args.password or "guest",
                port=str(args.port)
            )
        except Exception as e:
            print(f"Error connecting: {str(e)}")

    # Connect the aboutToQuit signal directly to the cleanup method
    app.aboutToQuit.connect(main_window.cleanup)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
    def prepare_container_widget(self):
        container_widget = QWidget()
        layout = QHBoxLayout()

        self.left_browser = FileBrowser("Local Files", self.session_id)
        self.right_browser = RemoteFileBrowser("Remote Files", self.session_id)

        layout.addWidget(self.left_browser)
        layout.addWidget(self.right_browser)

        self.left_browser.add_observer(self.right_browser)
        self.right_browser.add_observer(self.left_browser)
        self.backgroundThreadWindow.add_observee(self.right_browser)
        self.backgroundThreadWindow.add_observee(self.left_browser)

        container_widget.setLayout(layout)
        return container_widget
