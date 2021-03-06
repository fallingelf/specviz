"""
Define all the line list-based windows and dialogs
"""
import os

from qtpy.QtWidgets import (QWidget, QGridLayout, QHBoxLayout, QLabel,
                            QPushButton, QTabWidget, QVBoxLayout, QSpacerItem,
                            QSizePolicy, QToolBar, QLineEdit, QTabBar,
                            QAction, QTableView, QMainWindow, QHeaderView,
                            QAbstractItemView, QLayout, QTextBrowser, QComboBox,
                            QDialog, QErrorMessage)
from qtpy.QtGui import QIcon, QColor, QStandardItem, \
                       QDoubleValidator, QFont
from qtpy.QtCore import (Signal, QSize, QCoreApplication, QMetaObject, Qt,
                         QAbstractTableModel, QVariant, QSortFilterProxyModel)
from qtpy import compat
from qtpy.uic import loadUi

from astropy.units import Quantity
from astropy.units.core import UnitConversionError
from astropy.io import ascii

from ..core import linelist
from ..core.linelist import WAVELENGTH_COLUMN, ERROR_COLUMN, DEFAULT_HEIGHT
from ..core.linelist import columns_to_remove

ICON_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                         '..', 'data', 'qt', 'resources'))

# We need our own mapping because the list with color names returned by
# QColor.colorNames() is inconsistent with the color names in Qt.GlobalColor.
ID_COLORS = {
    'black':      Qt.black,
    'red':        Qt.red,
    'green':      Qt.green,
    'blue':       Qt.blue,
    'cyan':       Qt.cyan,
    'magenta':    Qt.magenta,
    'dark red':   Qt.darkRed,
    'dark green': Qt.darkGreen,
    'dark blue':  Qt.darkBlue
}

PLOTTED = "Plotted"
NLINES_WARN = 150

# Function that creates one single tabbed pane with one single view of a line list.

def _createLineListPane(linelist, table_model, caller):

    table_view = QTableView()

    # disabling sorting will significantly speed up the rendering,
    # in particular of large line lists. These lists are often jumbled
    # in wavelength, and consequently difficult to read and use, so
    # having a sorting option is useful indeed. It remains to be seen
    # what would be the approach users will favor. We might add a toggle
    # that users can set/reset depending on their preferences.
    table_view.setSortingEnabled(False)
    sort_proxy = SortModel(table_model.getName())
    sort_proxy.setSourceModel(table_model)

    table_view.setModel(sort_proxy)
    table_view.setSortingEnabled(True)
    table_view.horizontalHeader().setStretchLastSection(True)

    # playing with these doesn't speed up the sorting, regardless of whatever
    # you may read on the net.
    #
    # table_view.horizontalHeader().setResizeMode(QHeaderView.Fixed)
    # table_view.verticalHeader().setResizeMode(QHeaderView.Fixed)
    # table_view.horizontalHeader().setStretchLastSection(False)
    # table_view.verticalHeader().setStretchLastSection(False)
    table_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
    table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
    table_view.resizeColumnsToContents()

    # this preserves the original sorting state of the list. Use zero
    # to sort by wavelength on load. Doesn't seem to affect performance
    # by much tough.
    sort_proxy.sort(-1, Qt.AscendingOrder)

    # table selections will change the total count of lines selected.
    pane = LineListPane(table_view, linelist, sort_proxy, caller)

    return pane, table_view


# The line list window must be a full fledged window and not a dialog.
# Dialogs do not support things like menu bars and central widgets.
# They are also a bit cumbersome to use when modal behavior is of no
# importance. Lets try to treat this as a window for now, and see how
# it goes.

class ClosableMainWindow(QMainWindow):
    # This class exists just to ensure that a window closing event
    # that is generated by the OS itself, gets properly handled.
    def __init__(self, plot_window, parent=None):
        super(ClosableMainWindow, self).__init__()
        self.plot_window = plot_window

    def closeEvent(self, event):
        self.plot_window.dismiss_linelists_window.emit(False)


class LineListsWindow(ClosableMainWindow):

    def __init__(self, plot_window, parent=None):
        super(LineListsWindow, self).__init__(plot_window)

        self.plot_window = plot_window

        self.wave_range = (None, None)

        loadUi(os.path.join(os.path.dirname(__file__), "ui", "linelists_window.ui"), self)
        self.setWindowTitle(str(self.plot_window._title))

        # QtDesigner can't add a combo box to a tool bar...
        self.line_list_selector = QComboBox()
        self.line_list_selector.setToolTip("Select line list from internal library")
        self.mainToolBar.addWidget(self.line_list_selector)

        # QtDesigner creates tabbed widgets with 2 tabs, and doesn't allow
        # removing then in the designer itself. Remove in here then.
        while self.tabWidget.count() > 0:
            self.tabWidget.removeTab(0)

        # Request that line lists be read from wherever are they sources.
        plot_window.request_linelists()

        # Populate line list selector with internal line lists
        model = self.line_list_selector.model()
        item = QStandardItem("Select line list")
        font = QFont("Monospace")
        font.setStyleHint(QFont.TypeWriter)
        font.setPointSize(12)
        item.setFont(font)
        model.appendRow(item)
        for description in linelist.descriptions():
            item = QStandardItem(str(description))
            item.setFont(font)
            model.appendRow(item)

        #------------ UNCOMMENT TO LOAD LISTS AUTOMATICALLY --------------
        #
        # Populate GUI.
        #
        # This is commented out for now to comply with the decision about
        # not showing any line list automatically upon startup. In case
        # we need that capability back, just uncomment this line.

        # self._buildViews(plot_window)

        #---------------------------------------------------------------

        # Connect controls to appropriate signals.
        #
        # Note that, for the Draw operation, we have to pass the table views to
        # the handler, even though it would be better to handle the row selections
        # all in here for the sake of encapsulation. This used to be necessary
        # because this class is not a QWidget or one of its subclasses, thus it
        # cannot implement a DispatchHandle signal handler. Once we gt rid of the
        # Dispatch facility, this design decision could likely be modified. We
        # decide to keep the same old design for now, to prevent breaks in logic.

        self.draw_button.clicked.connect(
            lambda:self.plot_window.line_labels_plotter.plot_linelists(
                table_views=self._getTableViews(),
                panes=self._getPanes(),
                units=self.plot_window.spectral_axis_unit,
                caller=self.plot_window))

        self.erase_button.clicked.connect(lambda:self.plot_window.erase_linelabels.emit(self.plot_window))
        self.dismiss_button.clicked.connect(lambda:self.plot_window.dismiss_linelists_window.emit(False))
        self.actionOpen.triggered.connect(lambda:self._open_linelist_file(file_name=None))
        self.actionExport.triggered.connect(lambda:self._export_to_file(file_name=None))
        self.line_list_selector.currentIndexChanged.connect(self._lineList_selection_change)
        self.tabWidget.tabCloseRequested.connect(self.tab_close)

    def _get_waverange_from_dialog(self, line_list):
        # there is a widget-wide wavelength range so as to preserve
        # the user definition from call to call. At the initial
        # call, the wave range is initialized with whatever range
        # is being displayed in the spectrum plot window.
        if self.wave_range[0] == None or self.wave_range[1] == None:
            self.wave_range = self.plot_window._find_wavelength_range()

        wrange = self._build_waverange_dialog(self.wave_range, line_list)

        self.wave_range = wrange

    def _open_linelist_file(self, file_name=None):
        if file_name is None:

            filters = ['Line list (*.yaml *.ecsv)']
            file_name, _file_filter = compat.getopenfilenames(filters=";;".join(filters))

            # For now, lets assume both the line list itself, and its
            # associated YAML descriptor file, live in the same directory.
            # Not an issue for self-contained ecsv files.
            if file_name is not None and len(file_name) > 0:
                name = file_name[0]
                line_list = linelist.get_from_file(os.path.dirname(name), name)

                if line_list:
                    self._get_waverange_from_dialog(line_list)
                    if self.wave_range[0] and self.wave_range[1]:
                        line_list = self._build_view(line_list, 0, waverange=self.wave_range)
                        self.plot_window.linelists.append(line_list)

    def _export_to_file(self, file_name=None):
        if file_name is None:

            if hasattr(self, '_plotted_lines_pane') and self._plotted_lines_pane:

                filters = ['Line list (*.ecsv)']
                file_name, _file_filter = compat.getsavefilename(filters=";;".join(filters))

                if not file_name.endswith('.ecsv'):
                    file_name += '.ecsv'

                output_table = self._plotted_lines_pane.plotted_lines.table

                for colum_name in columns_to_remove:
                    if colum_name in output_table.colnames:
                        output_table.remove_column(colum_name)

                ascii.write(output_table, output=file_name, format='ecsv')

    def _lineList_selection_change(self, index):
        # ignore first element in drop down. It contains
        # the "Select line list" message.
        if index > 0:
            line_list = linelist.get_from_cache(index-1)

            try:
                self._get_waverange_from_dialog(line_list)
                if self.wave_range[0] and self.wave_range[1]:
                    self._build_view(line_list, 0, waverange=self.wave_range)

                self.line_list_selector.setCurrentIndex(0)

            except UnitConversionError as err:
                error_dialog = QErrorMessage()
                error_dialog.showMessage('Units conversion not possible.')
                error_dialog.exec_()

    def _build_waverange_dialog(self, wave_range, line_list):

        dialog = QDialog(parent=self.centralWidget)

        loadUi(os.path.join(os.path.dirname(__file__), "ui", "linelists_waverange.ui"), dialog)

        dialog.min_text.setText("%.2f" % wave_range[0].value)
        dialog.max_text.setText("%.2f" % wave_range[1].value)

        validator = QDoubleValidator()
        validator.setBottom(0.0)
        validator.setDecimals(2)
        dialog.min_text.setValidator(validator)
        dialog.max_text.setValidator(validator)

        dialog.nlines_label = self._compute_nlines_in_waverange(line_list, dialog.min_text, dialog.max_text,
                                                                dialog.nlines_label)

        dialog.min_text.editingFinished.connect(lambda: self._compute_nlines_in_waverange(line_list,
                                                 dialog.min_text, dialog.max_text, dialog.nlines_label))
        dialog.max_text.editingFinished.connect(lambda: self._compute_nlines_in_waverange(line_list,
                                                 dialog.min_text, dialog.max_text, dialog.nlines_label))

        accepted = dialog.exec_() > 0

        amin = amax = None
        if accepted:
            return self._get_range_from_textfields(dialog.min_text, dialog.max_text)

        return (amin, amax)

    def _get_range_from_textfields(self, min_text, max_text):
        amin = amax = None

        if min_text.hasAcceptableInput() and max_text.hasAcceptableInput():
            amin = float(min_text.text())
            amax = float(max_text.text())
            if amax != amin:
                units = self.plot_window.listDataItems()[0].spectral_axis_unit
                amin = Quantity(amin, units)
                amax = Quantity(amax, units)
            else:
                return (None, None)

        return (amin, amax)

    # computes how many lines in the supplied list
    # fall within the supplied wavelength range. The
    # result populates the supplied label. Or, it
    # builds a fresh QLabel with the result.
    def _compute_nlines_in_waverange(self, line_list, min_text, max_text, label):

        amin, amax = self._get_range_from_textfields(min_text, max_text)

        if amin != None or amax != None:
            r = (amin, amax)
            extracted = line_list.extract_range(r)
            nlines = len(extracted[WAVELENGTH_COLUMN].data)

            label.setText(str(nlines))
            color = 'black' if nlines < NLINES_WARN else 'red'
            label.setStyleSheet('color:' + color)

        return label

    def _build_view(self, line_list, index, waverange=(None,None)):

        if waverange[0] and waverange[1]:
            line_list = line_list.extract_range(waverange)

        table_model = LineListTableModel(line_list)

        if table_model.rowCount() > 0:
            # here we add the first pane (the one with the entire
            # original line list), to the tabbed pane that contains
            # the line sets corresponding to the current line list.
            lineset_tabbed_pane = QTabWidget()
            lineset_tabbed_pane.setTabsClosable(True)

            pane, table_view = _createLineListPane(line_list, table_model, self)
            lineset_tabbed_pane.addTab(pane, "Original")
            pane.setLineSetsTabbedPane(lineset_tabbed_pane)

            # connect signals
            table_view.selectionModel().selectionChanged.connect(self._countSelections)
            table_view.selectionModel().selectionChanged.connect(pane.handle_button_activation)

            # now we add this "line set tabbed pane" to the main tabbed
            # pane, with name taken from the list model.
            self.tabWidget.insertTab(index, lineset_tabbed_pane, table_model.getName())
            self.tabWidget.setCurrentIndex(index)

            # store for use down stream.
            # self.table_views.append(table_view)
            # self.set_tabbed_panes.append(set_tabbed_pane)
            # self.tab_count.append(0)
            # self.panes.append(pane)

            return line_list

    def _buildViews(self, plot_window):
        window_linelists = plot_window.linelists
        for linelist, index  in zip(window_linelists, range(len(window_linelists))):
            self._build_view(linelist, index)

        # add extra tab to hold the plotted lines view.
        widget_count = self.tabWidget.count()
        if widget_count > 0:
            self.tabWidget.addTab(QWidget(), PLOTTED)
            self.tabWidget.tabBar().setTabButton(widget_count-1, QTabBar.LeftSide, None)

    def tab_close(self, index):
        self.tabWidget.removeTab(index)

    def displayPlottedLines(self, linelist):
        self._plotted_lines_pane = PlottedLinesPane(linelist)

        for index in range(self.tabWidget.count()):
            tab_text = self.tabWidget.tabText(index)
            if tab_text == PLOTTED:
                self.tabWidget.removeTab(index)
                self.tabWidget.insertTab(index, self._plotted_lines_pane, PLOTTED)
                return

        # if no plotted pane yet, create one.
        index = self.tabWidget.count()
        self.tabWidget.insertTab(index, self._plotted_lines_pane, PLOTTED)

    def erasePlottedLines(self):
        index_last = self.tabWidget.count() - 1
        self.tabWidget.removeTab(index_last)

    # computes total of rows selected in all table views in all panes
    # and displays result in GUI.
    def _countSelections(self):
        panes = self._getPanes()
        sizes = [len(pane.table_view.selectionModel().selectedRows()) for pane in panes]
        import functools
        count = functools.reduce(lambda x,y: x+y, sizes)

        # display total selected rows, with eventual warning.
        self.lines_selected_label.setText(str(count))
        color = 'black' if count < NLINES_WARN else 'red'
        self.lines_selected_label.setStyleSheet('color:'+color)

    # these two methods below return a flat rendering of the panes
    # and table views stored in the two-tiered tabbed window. These
    # flat renderings are required by the drawing code.

    def _getTableViews(self):
        panes = self._getPanes()
        return [pane.table_view for pane in panes]

    def _getPanes(self):
        result = []
        for index_1 in range(self.tabWidget.count()):
            widget = self.tabWidget.widget(index_1)
            if isinstance(widget, QTabWidget) and self.tabWidget.tabText(index_1) != PLOTTED:
                # do not use list comprehension here!
                for index_2 in range(widget.count()):
                    result.append(widget.widget(index_2))
        return result


class LineListPane(QWidget):

    # this builds a single pane dedicated to a single list.

    def __init__(self, table_view, linelist, sort_proxy, caller, *args, **kwargs):
        super().__init__(None, *args, **kwargs)

        self.table_view = table_view
        self.linelist = linelist
        self._sort_proxy = sort_proxy
        self._caller = caller

        self._build_GUI(linelist, table_view)

    def _build_GUI(self, linelist, table_view):
        panel_layout = QVBoxLayout()
        panel_layout.setSizeConstraint(QLayout.SetMaximumSize)
        self.setLayout(panel_layout)

        # GUI cannot be completely defined in a .ui file.
        # It has to be built on-the-fly here.
        self.button_pane = QWidget()
        loadUi(os.path.join(os.path.dirname(__file__), "ui", "linelists_panel_buttons.ui"), self.button_pane)
        self.button_pane.create_set_button.clicked.connect(self._createSet)
        self.button_pane.deselect_button.clicked.connect(table_view.clearSelection)

        # header with line list metadata.
        info = QTextBrowser()
        info.setMaximumHeight(100)
        info.setAutoFillBackground(True)
        info.setStyleSheet("background-color: rgb(230,230,230);")
        for comment in linelist.meta['comments']:
            info.append(comment)

        # populate color picker
        model = self.button_pane.combo_box_color.model()
        for cname in ID_COLORS:
            item = QStandardItem(cname)
            item.setForeground(ID_COLORS[cname])
            item.setData(QColor(ID_COLORS[cname]), role=Qt.UserRole)
            model.appendRow(item)

        # set validators
        validator = QDoubleValidator()
        validator.setRange(0.05, 0.95, decimals=2)
        self.button_pane.height_textbox.setValidator(validator)
        validator = QDoubleValidator()
        validator.setRange(-1.e5, 1.e10, decimals=4)
        self.button_pane.redshift_textbox.setValidator(validator)

        model = self.button_pane.combo_box_z_units.model()
        for uname in ['z', 'km/s']:
            item = QStandardItem(uname)
            model.appendRow(item)

        # put it all together
        panel_layout.addWidget(info)
        panel_layout.addWidget(table_view)
        panel_layout.addWidget(self.button_pane)

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def setLineSetsTabbedPane(self, pane):
        self._sets_tabbed_pane = pane

        # this must be set only once per tabbed pane, otherwise multiple
        # signal handlers can result in more than one tab being closed
        # when just one closing request is posted.
        self._sets_tabbed_pane.tabCloseRequested.connect(self.tab_close)

    def _createSet(self):
        # build list with only the selected rows. These must be model
        # rows, not view rows!
        selected_view_rows = self.table_view.selectionModel().selectedRows()
        selected_model_rows = [self._sort_proxy.mapToSource(x) for x in selected_view_rows]

        if len(selected_model_rows) > 0:
            r = [x for x in selected_model_rows]
            local_list = self.linelist.extract_rows(r)

            # name is used to match lists with table views
            local_list.name = self.linelist.name

            table_model = LineListTableModel(local_list)
            pane, table_view = _createLineListPane(local_list, table_model, self._caller)

            pane._sets_tabbed_pane = self._sets_tabbed_pane
            table_view.selectionModel().selectionChanged.connect(self._caller._countSelections)
            table_view.selectionModel().selectionChanged.connect(pane.handle_button_activation)

            self._sets_tabbed_pane.addTab(pane, str(self._sets_tabbed_pane.count()))

    def tab_close(self, index):
        self._sets_tabbed_pane.removeTab(index)

    def handle_button_activation(self):
        nselected = len(self.table_view.selectionModel().selectedRows())
        self.button_pane.create_set_button.setEnabled(nselected > 0)


class PlottedLinesPane(QWidget):

    # This holds the list with the currently plotted lines.
    #
    # This view is re-built every time a new set of markers
    # is plotted. The list view build here ends up being the
    # main bottleneck in terms of execution time perceived by
    # the user (found this using cProfile). The time to build
    # the list is about the same as the time spent in the
    # paint() methods of all components in the plot, for a set
    # of a couple hundred markers. Most of that time in turn is
    # spent in the column resizing method in the table view. If
    # sorting is enabled for this view, times will increase
    # dramatically.
    #
    # This plotted lines pane represents one of the possible
    # implementations of the last requirement in Tony Marston's
    # line list document (option to show line information for
    # lines shown in the plot). Given the slowness of it, it
    # would be good to have feedback on this in order to try
    # alternate implementation approaches (a simple ASCII table
    # might suffice, perhaps). An alternate approach would be to
    # use some timing algorithm that will prevent the view to be
    # rebuilt rigth after a previous rebuilt. A time delay of sorts
    # could take care of that.

    def __init__(self, plotted_lines, *args, **kwargs):
        super().__init__(None, *args, **kwargs)

        self.plotted_lines = plotted_lines

        layout = QVBoxLayout()
        layout.setSizeConstraint(QLayout.SetMaximumSize)
        self.setLayout(layout)

        table_model = LineListTableModel(plotted_lines)
        if table_model.rowCount() > 0:
            table_view = QTableView()

            # disabling sorting will significantly speed up theWidget
            # plot. This is because the table view must be re-built
            # every time a new set of markers is drawn on the plot
            # surface. Alternate approaches are worth examining. It
            # remains to be seen what would be the approach users
            # will favor.

            table_view.setSortingEnabled(False)
            proxy = SortModel(table_model.getName())
            proxy.setSourceModel(table_model)
            table_view.setModel(proxy)
            table_view.setSortingEnabled(True)

            table_view.setSelectionMode(QAbstractItemView.NoSelection)
            table_view.horizontalHeader().setStretchLastSection(True)
            table_view.resizeColumnsToContents()

            layout.addWidget(table_view)


class LineListTableModel(QAbstractTableModel):

    def __init__(self, linelist, parent=None, *args):

        QAbstractTableModel.__init__(self, parent, *args)

        self._linelist = linelist

        #TODO move entire table contents to an array of QVector
        # instances that will store the columns. This should
        # speed up the sorting (as far as some indications in
        # the net suggest:
        # http://www.qtforum.org/article/30638/qsortfilterproxymodel-qtreeview-sort-performance.html).
        # Bummer... this is C++ only; PyQt never went to the trouble
        # of converting QVector to python.
        #
        # get rid entirely of astropy table and store its contents in
        # a 2-D list of lists. By using python lists instead of an
        # astropy table, and storing the QVariant instances instead
        # of the raw content, we can speed up sorting by a factor > 10X.

        # we have to do this here because some lists may
        # have no lines at all.
        self._nrows = 0
        self._ncols = 0

        self._row_cells = []

        for row in self._linelist:
            cells = []
            for rindex in range(len(row)):
                cell = row[rindex]

                # handling of a color object can be tricky. Color names
                # returned by QColor.colorNames() are inconsistent with
                # color names in Qt.GlobalColor. We just go to the basics
                # and compare color equality (or closeness) using a distance
                # criterion in r,g,b coordinates.
                # Although costly, this would be a CPU burden only when
                # sorting columns with color information. For now, only
                # the Plotted Lines line list has such information, and
                # the number of actually plotted lines tends to be small
                # anyway.
                if isinstance(cell, QColor):
                    r = cell.red()
                    g = cell.green()
                    b = cell.blue()
                    min_dist = 100000
                    result = cell
                    for color_name, orig_color in ID_COLORS.items():
                        orig_rgb = QColor(orig_color)
                        dist = abs(orig_rgb.red() - r) + abs(orig_rgb.green() - g) + abs(orig_rgb.blue() - b)
                        if dist < min_dist:
                            min_dist = dist
                            result = orig_color

                    key = [k for k,value in ID_COLORS.items() if value == result][0]

                    cells.append(QVariant(key))

                else:
                    cells.append(QVariant(str(cell)))

            self._row_cells.append(cells)

            self._nrows = len(self._row_cells)
            self._ncols = len(self._row_cells[0])

    def rowCount(self, parent=None, *args, **kwargs):
        # this has to use a pre-computed number of rows,
        # otherwise sorting gets significantly slowed
        # down. Same for number of columns.
        return self._nrows

    def columnCount(self, parent=None, *args, **kwargs):
        return self._ncols

    def data(self, index, role=None):
        if role != Qt.DisplayRole:
            return QVariant()

        # This is the main bottleneck for sorting. Profiling experiments
        # show that the main culprit is the .columns[][] accessor in the
        # astropy table. The index.column() and index.row() calls cause
        # negligible CPU load.
        #
        # return self._linelist.columns[index.column()][index.row()]
        #
        # going from an astropy table to a list of rows, the bottleneck
        # narrows down to the astropy code that gets a cell value from a
        # Row instance.
        return self._row_cells[index.row()][index.column()]

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._linelist.colnames[section]

        # This generates tooltips for header cells
        if role == Qt.ToolTipRole and orientation == Qt.Horizontal:
            if self._linelist.colnames[section] in [WAVELENGTH_COLUMN, ERROR_COLUMN]:
                result = self._linelist.columns[section].unit
            else:
                # this captures glitches that generate None tooltips
                if self._linelist.tooltips:
                    result = self._linelist.tooltips[section]
                else:
                    result = ''
            return str(result)

        return QAbstractTableModel.headerData(self, section, orientation, role)

    def getName(self):
        return self._linelist.name


class SortModel(QSortFilterProxyModel):

    def __init__(self, name):
        super(SortModel, self).__init__()

        self._name = name

    def lessThan(self, left, right):
        left_data = left.data()
        right_data = right.data()

        # it's enough to find type using just one of the parameters,
        # since they both necessarily come from the same table column.
        try:
            l = float(left_data)
            r = float(right_data)
            return l < r
        except:
            # Lexicographic string comparison. The parameters passed
            # to this method from a sortable table model are stored
            # in QtCore.QModelIndex instances.
            return str(left_data) < str(right_data)

    def getName(self):
        return self._name


