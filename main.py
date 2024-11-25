import sys
import random
import math
from UiMainWindow import Ui_MainWindow
from UiStartupDialog import Ui_StartupDialog
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QDialog,
                             QPushButton, QLabel, QSpinBox, QDoubleSpinBox,
                             QSlider, QTableWidget, QTableWidgetItem,
                             QHBoxLayout, QVBoxLayout, QSpacerItem, QSizePolicy,
                             QSplitter, QLineEdit, QMessageBox)
from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal


class Order:
    clientNextOrderId = {}

    @staticmethod
    def makeOrder(clientId, creationTime):
        if clientId in Order.clientNextOrderId:
            orderId = Order.clientNextOrderId[clientId]
            Order.clientNextOrderId[clientId] += 1
        else:
            Order.clientNextOrderId[clientId] = 1
            orderId = 0
        return Order(clientId, orderId, f"И{clientId}_{orderId}", creationTime)

    def __init__(self, clientId, orderId, name, creationTime):
        self.clientId_ = clientId
        self.orderId_ = orderId
        self.name_ = name
        self.creationTime_ = creationTime

    def name(self):
        return self.name_

    def clientId(self):
        return self.clientId_

    def creationTime(self):
        return self.creationTime_

    def __eq__(self, rhs):
        return self.clientId_ == rhs.clientId_ and self.orderId_ == rhs.orderId_


class EventType:
    ORDER_CREATED = 0
    DEVICE_FINISHED = 1

    def __init__(self, type):
        self.type_ = type

    def __eq__(self, rhs):
        return self.type_ == rhs.type_

    def to_string(self):
        if self.type_ == EventType.ORDER_CREATED:
            return "ORDER_CREATED"
        elif self.type_ == EventType.DEVICE_FINISHED:
            return "DEVICE_FINISHED"
        else:
            raise ValueError("Unknown event type")


class Event:
    def __init__(self, type, time, order):
        self.type_ = type
        self.time_ = time
        self.order_ = order

    def type(self):
        return self.type_

    def time(self):
        return self.time_

    def order(self):
        return self.order_

    def __lt__(self, rhs):  # For set comparison
        return self.time_ < rhs.time_


class Buffer(QObject):
    orderRejected = pyqtSignal(Order, float)

    def __init__(self, bufferSize, bufferGui, eventsGui):
        super().__init__()
        self.queue_ = []  # Implementing circular buffer with list and modulo operator
        self.bufferSize_ = bufferSize
        self.bufferGui_ = bufferGui
        self.eventsGui_ = eventsGui

    def addOrder(self, order, time):
        if len(self.queue_) == self.bufferSize_:
            orderToReject = self.queue_.pop(0)
            self.eventsGui_.addEvent(time, orderToReject, "REJECTED")
            self.eventsGui_.addCanceled()
            self.orderRejected.emit(orderToReject, time)
            self.queue_.append(order)
            self.eventsGui_.addEvent(time, order, "PUT IN BUFFER")
            self.bufferGui_.pop_front()
            self.bufferGui_.push_back(order)
        else:
            self.queue_.append(order)
            self.eventsGui_.addEvent(time, order, "PUT IN BUFFER")
            self.bufferGui_.push_back(order)

    def popOrder(self, time):
        if self.queue_:
            order = self.queue_.pop(0)
            self.eventsGui_.addEvent(time, order, "OUT OF BUFFER")
            self.bufferGui_.pop_front()
        else:
            raise IndexError("Pop from an empty queue")

    def nextOrder(self):
        if not self.queue_:
            raise IndexError("Next order requested from empty queue")

        return self.queue_[0]

    def hasSpace(self):
        return len(self.queue_) < self.bufferSize_

    def empty(self):
        return not self.queue_


class DeviceHolder:
    class Device:
        def __init__(self, id, minProcessingTime, maxProcessingTime):
            self.id_ = id
            self.minTime_ = minProcessingTime
            self.maxTime_ = maxProcessingTime
            self.order_ = None
            self.finishTime_ = 0

        def isFree(self, time):
            return not self.order_ or self.finishTime_ <= time

        def processOrder(self, order, startTime):
            self.order_ = order
            self.finishTime_ = startTime + random.uniform(self.minTime_, self.maxTime_)
            return self.finishTime_

    def __init__(self, nDevices, minProcessingTime, maxProcessingTime):
        self.devices_ = {deviceId: self.Device(deviceId, minProcessingTime, maxProcessingTime) for deviceId in
                         range(nDevices)}

    def processOrder(self, order, time):
        for device in self.devices_.values():
            if device.isFree(time):
                return device.processOrder(order, time)
        raise RuntimeError("No free devices")

    def hasSpace(self, time):
        return any(device.isFree(time) for device in self.devices_.values())


class Statistics(QObject):
    def __init__(self, nDevices):
        super().__init__()
        self.nSuccess_ = 0
        self.nRejected_ = 0
        self.orderTimesInSystem_ = []
        self.devicesTime_ = 0
        self.nDevices_ = nDevices
        self.lastFinishedOrderTime_ = 0

    def addSuccessOrder(self, order, finishTime):
        self.nSuccess_ += 1
        self.lastFinishedOrderTime_ = finishTime
        self.addAvgTime(order, finishTime)

    def addRejected(self, order, finishTime):
        self.nRejected_ += 1
        self.lastFinishedOrderTime_ = finishTime
        self.addAvgTime(order, finishTime)

    def addDeviceProcessingTime(self, startTime, finishTime):
        if startTime > finishTime: raise ValueError("Start time cannot be greater than finish time")

        self.devicesTime_ += finishTime - startTime

    def getRejectProbability(self):
        total = self.nRejected_ + self.nSuccess_
        return self.nRejected_ / total if total else 0

    def getAvgTimeInSystem(self):
        return sum(self.orderTimesInSystem_) / len(self.orderTimesInSystem_) if self.orderTimesInSystem_ else 0

    def getDeviceLoad(self):
        return self.devicesTime_ / (self.lastFinishedOrderTime_ * self.nDevices_) if self.lastFinishedOrderTime_ else 0

    def addAvgTime(self, order, finishTime):
        self.orderTimesInSystem_.append(finishTime - order.creationTime())


class BufferGui:
    class Column:  # Using nested class for enum
        INDEX = 0
        PUSH = 1
        ORDER = 2
        POP = 3

    def __init__(self, table, bufferSize):
        self.table_ = table
        self.size_ = bufferSize
        self.pushIndex = 0
        self.popIndex = 0

        itemProto = QTableWidgetItem("")
        itemProto.setTextAlignment(Qt.AlignCenter)
        itemProto.setFlags(itemProto.flags() & ~(Qt.ItemIsEditable | Qt.ItemIsSelectable))

        for index in range(self.size_):
            newRow = self.table_.rowCount()
            self.table_.insertRow(newRow)

            indexItem = itemProto.clone()
            indexItem.setText(str(newRow))
            self.table_.setItem(newRow, self.Column.INDEX, indexItem)

            pushItem = itemProto.clone()
            if index == 0:
                pushItem.setText("---->".center(50))  # Adjust to see in table
            boldFont = pushItem.font()
            boldFont.setBold(True)
            boldFont.setPointSize(14)
            pushItem.setFont(boldFont)
            self.table_.setItem(newRow, self.Column.PUSH, pushItem)

            self.table_.setItem(newRow, self.Column.ORDER, itemProto.clone())

            popItem = itemProto.clone()
            if index == 0:
                popItem.setText("<----".center(50))  # Adjust to see in table
            popItem.setFont(boldFont)
            self.table_.setItem(newRow, self.Column.POP, popItem)

    def push_back(self, order):
        orderItem = QTableWidgetItem(order.name())
        orderItem.setTextAlignment(Qt.AlignCenter)
        orderItem.setFlags(orderItem.flags() & ~(Qt.ItemIsEditable | Qt.ItemIsSelectable))
        self.table_.setItem(self.pushIndex, self.Column.ORDER, orderItem)
        self.pushIndex = (self.pushIndex + 1) % self.size_
        self.movePushCursor()

    def pop_front(self):

        emptyItem = QTableWidgetItem("")
        emptyItem.setTextAlignment(Qt.AlignCenter)
        emptyItem.setFlags(emptyItem.flags() & ~(Qt.ItemIsEditable | Qt.ItemIsSelectable))
        self.table_.setItem(self.popIndex, self.Column.ORDER, emptyItem)
        self.popIndex = (self.popIndex + 1) % self.size_
        self.movePopCursor()

    def movePushCursor(self):
        if self.pushIndex == 0:
            prevPushItem = self.table_.takeItem(self.size_ - 1, self.Column.PUSH)
            nextPushItem = self.table_.takeItem(0, self.Column.PUSH)
            self.table_.setItem(self.size_ - 1, self.Column.PUSH, nextPushItem)
            self.table_.setItem(0, self.Column.PUSH, prevPushItem)
        else:
            prevPushItem = self.table_.takeItem(self.pushIndex - 1, self.Column.PUSH)
            nextPushItem = self.table_.takeItem(self.pushIndex, self.Column.PUSH)
            self.table_.setItem(self.pushIndex - 1, self.Column.PUSH, nextPushItem)
            self.table_.setItem(self.pushIndex, self.Column.PUSH, prevPushItem)

    def movePopCursor(self):
        if self.popIndex == 0:
            prevPushItem = self.table_.takeItem(self.size_ - 1, self.Column.POP)
            nextPushItem = self.table_.takeItem(0, self.Column.POP)
            self.table_.setItem(self.size_ - 1, self.Column.POP, nextPushItem)
            self.table_.setItem(0, self.Column.POP, prevPushItem)

        else:
            prevPushItem = self.table_.takeItem(self.popIndex - 1, self.Column.POP)
            nextPushItem = self.table_.takeItem(self.popIndex, self.Column.POP)
            self.table_.setItem(self.popIndex - 1, self.Column.POP, nextPushItem)
            self.table_.setItem(self.popIndex, self.Column.POP, prevPushItem)


class ClientsGui:
    class Column:
        INDEX = 0
        TIME = 1
        ORDER_NAME = 2

    def __init__(self, table, nClients):
        self.table_ = table

        itemProto = QTableWidgetItem("")
        itemProto.setTextAlignment(Qt.AlignCenter)
        itemProto.setFlags(itemProto.flags() & ~(Qt.ItemIsEditable | Qt.ItemIsSelectable))

        for index in range(nClients):
            newRow = self.table_.rowCount()
            self.table_.insertRow(newRow)

            indexItem = itemProto.clone()
            indexItem.setText(str(index))
            self.table_.setItem(newRow, self.Column.INDEX, indexItem)

            self.table_.setItem(newRow, self.Column.TIME, itemProto.clone())
            self.table_.setItem(newRow, self.Column.ORDER_NAME, itemProto.clone())

    def update(self, order):
        timeItem = QTableWidgetItem(str(order.creationTime()))
        timeItem.setTextAlignment(Qt.AlignCenter)
        self.table_.setItem(order.clientId(), self.Column.TIME, timeItem)

        orderItem = QTableWidgetItem(order.name())
        orderItem.setTextAlignment(Qt.AlignCenter)
        self.table_.setItem(order.clientId(), self.Column.ORDER_NAME, orderItem)


class DevicesGui:
    class Device:
        def __init__(self, index):
            self.index_ = index
            self.isFree_ = True
            self.order_ = None

        def processOrder(self, order):
            self.order_ = order
            self.isFree_ = False

        def finishProcessing(self):
            self.isFree_ = True

        def isFree(self):
            return self.isFree_

        def index(self):
            return self.index_

        def __eq__(self, order):
            return not self.isFree_ and self.order_ == order

        def __bool__(self):  # Implementing bool operator
            return self.isFree_

    class Column:
        INDEX = 0
        ORDER = 1
        FINISH_TIME = 2

    def __init__(self, table, nDevices):
        self.table_ = table
        self.devices_ = [self.Device(index) for index in range(nDevices)]

        itemProto = QTableWidgetItem("")
        itemProto.setTextAlignment(Qt.AlignCenter)
        itemProto.setFlags(itemProto.flags() & ~(Qt.ItemIsEditable | Qt.ItemIsSelectable))

        for index in range(nDevices):
            newRow = self.table_.rowCount()
            self.table_.insertRow(newRow)

            indexItem = itemProto.clone()
            indexItem.setText(str(newRow))
            self.table_.setItem(newRow, self.Column.INDEX, indexItem)

            self.table_.setItem(newRow, self.Column.ORDER, itemProto.clone())
            self.table_.setItem(newRow, self.Column.FINISH_TIME, itemProto.clone())

    def process(self, order, finishTime):
        for device in self.devices_:
            if device:
                device.processOrder(order)

                orderItem = QTableWidgetItem(order.name())
                orderItem.setTextAlignment(Qt.AlignCenter)
                self.table_.setItem(device.index(), self.Column.ORDER, orderItem)

                finishTimeItem = QTableWidgetItem(str(finishTime))
                finishTimeItem.setTextAlignment(Qt.AlignCenter)
                self.table_.setItem(device.index(), self.Column.FINISH_TIME, finishTimeItem)
                return

        raise RuntimeError("No free devices")

    def finishProcessing(self, order):
        for device in self.devices_:
            if device == order:
                device.finishProcessing()

                emptyItem = QTableWidgetItem("")
                emptyItem.setTextAlignment(Qt.AlignCenter)
                self.table_.setItem(device.index(), self.Column.ORDER, emptyItem)
                self.table_.setItem(device.index(), self.Column.FINISH_TIME, emptyItem)

                return

        raise ValueError("Order not found in any device")


class EventsGui:
    class Column:
        TIME = 0
        ORDER = 1
        DESCRIPTION = 2

    def __init__(self, table, successSpin, canceledSpin):
        self.table_ = table
        self.successSpin_ = successSpin
        self.canceledSpin_ = canceledSpin

        itemProto = QTableWidgetItem("")
        itemProto.setTextAlignment(Qt.AlignCenter)
        itemProto.setFlags(itemProto.flags() & ~(Qt.ItemIsEditable | Qt.ItemIsSelectable))
        self.itemProto_ = itemProto

    def addEvent(self, time, order, description):
        newRow = self.table_.rowCount()
        self.table_.insertRow(newRow)

        timeItem = self.itemProto_.clone()
        timeItem.setText(str(time))
        self.table_.setItem(newRow, self.Column.TIME, timeItem)

        orderItem = self.itemProto_.clone()
        orderItem.setText(order.name())
        self.table_.setItem(newRow, self.Column.ORDER, orderItem)

        descrItem = self.itemProto_.clone()
        descrItem.setText(description)
        self.table_.setItem(newRow, self.Column.DESCRIPTION, descrItem)

        self.table_.scrollToBottom()

    def addSuccess(self):
        self.successSpin_.setValue(self.successSpin_.value() + 1)

    def addCanceled(self):
        self.canceledSpin_.setValue(self.canceledSpin_.value() + 1)


class InputParameters:
    def __init__(self, nDevices=5, nClients=5, time=5, bufferSize=5,
                 minDeviceTime=0.1, maxDeviceTime=1, lambda_=0.5):
        self.nDevices = nDevices
        self.nClients = nClients
        self.time = time
        self.bufferSize = bufferSize
        self.minDeviceTime = minDeviceTime
        self.maxDeviceTime = maxDeviceTime
        self.lambda_ = lambda_

class EventHolder(QObject):

    def __init__(self, params, bufferGui, devicesGui, eventsGui, clientsGui):
        super().__init__()
        self.params_ = params
        self.bufferGui_ = bufferGui
        self.devicesGui_ = devicesGui
        self.eventsGui_ = eventsGui
        self.clientsGui_ = clientsGui

        self.deviceHolder_ = DeviceHolder(params.nDevices, params.minDeviceTime, params.maxDeviceTime)
        self.buffer_ = Buffer(params.bufferSize, bufferGui, eventsGui)
        self.stats_ = Statistics(params.nDevices)

        self.buffer_.orderRejected.connect(self.stats_.addRejected)

        self.calcEventsInterval()
        print("Interval:", self.eventsInterval_)

        self.events_ = set()  # Using set for ordered storage and fast operations
        currentTime = 0
        clientId = 0
        while currentTime < params.time:
            order = Order.makeOrder(clientId % params.nClients, currentTime)
            self.events_.add(Event(EventType(EventType.ORDER_CREATED), currentTime, order))
            self.calcEventsInterval()
            currentTime += self.eventsInterval_
            clientId += 1

        # Update clients GUI for initially created orders
        for event in sorted(self.events_)[:params.nClients]:  # Sort to ensure order
            self.clientsGui_.update(event.order())

    def step(self):
        if not self.events_:
            return

        event = min(self.events_)  # Get the earliest event
        self.events_.remove(event)
        self.processEvent(event)

    def isFinished(self):
        return not self.events_

    def getRejectProbability(self):
        return self.stats_.getRejectProbability()

    def getAvgTimeInSystem(self):
        return self.stats_.getAvgTimeInSystem()

    def getDeviceLoad(self):
        return self.stats_.getDeviceLoad()

    def calcEventsInterval(self):
        self.eventsInterval_ = -1 / self.params_.lambda_ *math.log(random.uniform(0.3, 0.6))

    def processEvent(self, event):
        if event.type() == EventType(EventType.ORDER_CREATED):
            self.processOrderCreatedEvent(event)
        elif event.type() == EventType(EventType.DEVICE_FINISHED):
            self.processDeviceFinishedEvent(event)
        else:
            raise ValueError("Unknown Event type")

    def processOrderCreatedEvent(self, event):
        if event.type() != EventType(EventType.ORDER_CREATED):
            raise ValueError("Incorrect event type for processOrderCreatedEvent")

        nextCreated = next((e for e in self.events_ if
                            e.order().clientId() == event.order().clientId() and e.type() == EventType(
                                EventType.ORDER_CREATED)), None)
        if nextCreated:
            self.clientsGui_.update(nextCreated.order())

        self.eventsGui_.addEvent(event.time(), event.order(), "CREATED")

        if self.deviceHolder_.hasSpace(event.time()):
            self.buffer_.addOrder(event.order(), event.time())
            self.buffer_.popOrder(event.time())
            finishTime = self.processOrder(event.order(), event.time())

            deviceFinishedEvent = Event(EventType(EventType.DEVICE_FINISHED), finishTime, event.order())

            self.events_.add(deviceFinishedEvent)
        else:
            self.buffer_.addOrder(event.order(), event.time())

    def processDeviceFinishedEvent(self, event):
        if event.type() != EventType(EventType.DEVICE_FINISHED):
            raise ValueError("Incorrect event type for processDeviceFinishedEvent")

        self.finishProcessing(event.order(), event.time())

        if not self.buffer_.empty():
            orderToProcess = self.buffer_.nextOrder()
            self.buffer_.popOrder(event.time())
            finishTime = self.processOrder(orderToProcess, event.time())

            deviceFinishedEvent = Event(EventType(EventType.DEVICE_FINISHED), finishTime, orderToProcess)

            self.events_.add(deviceFinishedEvent)

    def processOrder(self, order, time):
        finishTime = self.deviceHolder_.processOrder(order, time)
        self.stats_.addDeviceProcessingTime(time, finishTime)
        self.devicesGui_.process(order, finishTime)
        self.eventsGui_.addEvent(time, order, "PUT IN DEVICE")
        return finishTime

    def finishProcessing(self, order, time):
        self.eventsGui_.addEvent(time, order, "OUT OF DEVICE")
        self.devicesGui_.finishProcessing(order)
        self.eventsGui_.addSuccess()
        self.stats_.addSuccessOrder(order, time)



class StartupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui_ = Ui_StartupDialog()
        self.ui_.setupUi(self)

    def devicesCount(self):
        return self.ui_.devicesSpin.value()

    # ... (Other getters remain largely unchanged)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui_ = Ui_MainWindow()
        self.ui_.setupUi(self)

        for i in range(self.ui_.splitter.count()):
            self.ui_.splitter.setCollapsible(i, False)

        # Debug mode settings (you can adjust these)
        debug_params = InputParameters(nDevices=5, nClients=10, time=10,
                                       bufferSize=5, minDeviceTime=1,
                                       maxDeviceTime=2, lambda_=3)

        if '--no-debug' not in sys.argv:
            self.initParams(debug_params)
        else:
            QTimer.singleShot(0, self.execStartupWindow)

    def step(self):
        if self.eventHolder_.isFinished():
            self.ui_.statusLine.setText("Finished")
            return
        self.eventHolder_.step()
        self.updateStatistics()
        if self.eventHolder_.isFinished():
            self.ui_.statusLine.setText("Finished")

    def finish(self):
        if self.eventHolder_.isFinished():
            self.ui_.statusLine.setText("Finished")
            return

        while not self.eventHolder_.isFinished():
            self.eventHolder_.step()
            self.updateStatistics()

        self.ui_.statusLine.setText("Finished")

    def execStartupWindow(self):
        dialog = StartupDialog(self)
        while True:
            res = dialog.exec_()
            if res == QDialog.Rejected:
                QApplication.quit()
            if dialog.maxDeviceTime() < dialog.minDeviceTime():
                QMessageBox.warning(self, "Bad value",
                                    "max device time must be less than min device time")
                continue
            break

        params = InputParameters(nDevices=dialog.devicesCount(), nClients=dialog.clientsCount(),
                                 time=dialog.time(), bufferSize=dialog.bufferSize(),
                                 minDeviceTime=dialog.minDeviceTime(), maxDeviceTime=dialog.maxDeviceTime(),
                                 lambda_=dialog.lambda_())

        self.initParams(params)

    def updateStatistics(self):
        self.ui_.calcelProbSpin.setValue(self.eventHolder_.getRejectProbability())
        self.ui_.avgTimeSpin.setValue(self.eventHolder_.getAvgTimeInSystem())
        self.ui_.deviceLoadSpin.setValue(self.eventHolder_.getDeviceLoad())

    def initParams(self, params):
        self.eventsGui_ = EventsGui(self.ui_.eventsTable, self.ui_.successSpin, self.ui_.calceledSpin)
        self.bufferGui_ = BufferGui(self.ui_.bufferTable, params.bufferSize)
        self.devicesGui_ = DevicesGui(self.ui_.devicesTable, params.nDevices)
        self.clientsGui_ = ClientsGui(self.ui_.clientsTable, params.nClients)
        self.eventHolder_ = EventHolder(params, self.bufferGui_, self.devicesGui_, self.eventsGui_, self.clientsGui_)

        self.ui_.stepBtn.clicked.connect(self.step)
        self.ui_.autoBtn.clicked.connect(self.finish)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())