import sys
import time
import pandas as pd

from pathlib import Path
from typing import Callable
from PyQt6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QApplication,
    QCheckBox,
)
from PyQt6.QtCore import QThread, pyqtSignal


GUI_DIR = Path(__file__).parent.parent
GUI_SRC = GUI_DIR / "gui_src"
PROJECT_DIR = GUI_DIR.parent
CONFIG_PATH = PROJECT_DIR / "config" / "measures_config" / "setups"

sys.path.append(str(PROJECT_DIR))

from gui_common import CommonGUI
from src.semantix.measures_extraction import MeasuresExtractor, MeasuresGracefullExit
from src.semantix.cross_semantic import CrosserPro, LanguageRules, CrosserGracefullExit


SEMANTIX_CLIENT_COL = "Название клиента"
OUTPUT_FILENAME = "Semantix_output.xlsx"


class SemantixGracefullExit(Exception):
    pass


class RunButtonStatus(object):
    RUNNIG = "Остановить"
    STOPPED = "Начать обработку"
    STOPPING = "Останавливаю обработку"


class SemantixProcessRunner(QThread):
    progress_signal = pyqtSignal(int)

    def __init__(
        self,
        config: str | Path,
        data_path: str | Path,
        column: str,
        cross_sem_langs: list[str] = ["ru", "eng"],
        status_callback: Callable = None,
        progress_callback: Callable = None,
        run_button_callback: Callable = None,
    ) -> None:
        super().__init__()

        self.data_path = data_path
        self.column = column

        self.extractor = MeasuresExtractor(
            config,
            True,
            status_callback,
            self.call_progress,
        )

        crosser_lang_rules = self.setup_crosser_lang_rules(cross_sem_langs)
        self.crosser = CrosserPro(
            crosser_lang_rules,
            delete_rx=True,
            process_nearest=250,
            status_callback=status_callback,
            progress_callback=self.call_progress,
        )

        self.status_callback = status_callback
        self.progress_callback = progress_callback
        self.run_button_callback = run_button_callback

        self._stopped = False

    def upload_data(self):
        if ".csv" in self.data_path:
            data = pd.read_csv(self.data_path)
        elif ".xlsx" in self.data_path:
            data = pd.read_excel(self.data_path)
        else:
            raise ValueError("File should be Excel or csv")
        return data

    def setup_crosser_lang_rules(
        self,
        use_languages: list[str],
    ) -> list[LanguageRules]:
        langs = []

        if "ru" in use_languages:
            langs.append(
                LanguageRules(
                    "russian",
                    check_letters=True,
                    with_numbers=True,
                    min_lenght=3,
                    stemming=True,
                    symbols="",
                )
            )

        if "eng" in use_languages:
            langs.append(
                LanguageRules(
                    "english",
                    check_letters=True,
                    with_numbers=True,
                    min_lenght=3,
                    stemming=True,
                    symbols="",
                )
            )

        return langs

    def stop_callback(self):
        self.run_button_callback(RunButtonStatus.STOPPING)

        self._stopped = True
        self.extractor.stop_callback()
        self.crosser.stop_callback()

    def call_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)

    def call_progress(self, progress: int) -> None:
        self.progress_signal.emit(progress)

    def run_measure_extraction(self, data: pd.DataFrame) -> pd.DataFrame:
        try:
            self.call_status("Запускаю извлечение величин")
            data = self.extractor.extract(data, self.column, concat_regex=True)
            return data

        except MeasuresGracefullExit:
            raise SemantixGracefullExit

    def run_cross_semantic(self, data: pd.DataFrame) -> pd.DataFrame:
        try:
            self.call_status("Запускаю извлечение кросс-семантики")
            data = self.crosser.extract(data, self.column)
            return data

        except CrosserGracefullExit:
            raise SemantixGracefullExit

    def run(self) -> None:
        try:
            self.call_status("Загружаю данные")
            data = self.upload_data()

            data = self.run_measure_extraction(data)
            data = self.run_cross_semantic(data)

            self.call_status("Сохраняю результат")
            data.to_excel(PROJECT_DIR / OUTPUT_FILENAME, index=False)

            self.call_status("Сохранено")
            if self.run_button_callback is not None:
                self.run_button_callback(RunButtonStatus.STOPPED)

        except SemantixGracefullExit:
            self.call_status("Остановлено")
            self.call_progress(0)

            if self.run_button_callback is not None:
                self.run_button_callback(RunButtonStatus.STOPPED)


class SemantixWidget(CommonGUI):
    CONFIG_PATH = CONFIG_PATH

    def __init__(self):
        super().__init__()

        self.extractor: QThread = None
        main_layout = QVBoxLayout(self)

        self.workfile_lay = self._setup_workfile_layout(main_layout)
        self.config_lay = self._setup_config_layout(main_layout)
        self.cross_sem_langs = self._setup_cross_sem(main_layout)
        self.workcol_display = self._setup_runner(main_layout)

        self.status_bar = self._setup_status_bar(main_layout)
        self.status_callback("Ожидаю запуска")

        self.progress_bar = self._setup_progress_bar(main_layout)

        self.table_lay = self._setup_table_view(main_layout)

    def _setup_runner(self, main_layout: QVBoxLayout) -> None:
        workcol_layout = QHBoxLayout()
        workcol_label = QLabel("Столбец для обработки")
        self.workcol_display = QLineEdit(SEMANTIX_CLIENT_COL)
        workcol_layout.addWidget(workcol_label)
        workcol_layout.addWidget(self.workcol_display)

        runner_layout = QHBoxLayout()
        run_button = QPushButton(RunButtonStatus.STOPPED)
        run_button.clicked.connect(self.run_button_handler)
        runner_layout.addWidget(run_button)

        main_layout.addLayout(workcol_layout)
        main_layout.addLayout(runner_layout)

        self.run_button = run_button
        return self.workcol_display

    def _setup_cross_sem(self, main_layout: QVBoxLayout) -> list[QCheckBox]:
        cross_sem_langs = []
        cross_sem_layout = QHBoxLayout()

        label = QLabel("Языки для кросс-семантики: ")

        ru_cross_sem = QCheckBox("ru")
        ru_cross_sem.setChecked(True)
        cross_sem_langs.append(ru_cross_sem)

        eng_cross_sem = QCheckBox("eng")
        eng_cross_sem.setChecked(True)
        cross_sem_langs.append(eng_cross_sem)

        cross_sem_layout.addWidget(label)
        cross_sem_layout.addWidget(ru_cross_sem)
        cross_sem_layout.addWidget(eng_cross_sem)

        main_layout.addLayout(cross_sem_layout)
        return cross_sem_langs

    def run_button_status(self, status: RunButtonStatus) -> None:
        self.run_button.setText(status)

    def run_button_handler(self):
        if self.run_button.text() == RunButtonStatus.STOPPED:
            self.run()
        elif self.run_button.text() == RunButtonStatus.RUNNIG:
            self.stop()
        elif self.run_button.text() == RunButtonStatus.STOPPING:
            pass

    def run(self) -> None:
        self.run_button_status(RunButtonStatus.RUNNIG)

        config_path = self.CONFIG_PATH / self.config_combobox.currentText()
        config = self.read_config(config_path)

        cross_sem_langs = []
        for lang in self.cross_sem_langs:
            if lang.isChecked():
                cross_sem_langs.append(lang.text())

        self.extractor = SemantixProcessRunner(
            config,
            self.file_path_display.text(),
            self.workcol_display.text(),
            cross_sem_langs,
            status_callback=self.status_callback,
            progress_callback=self.progress_callback,
            run_button_callback=self.run_button_status,
        )

        self.extractor.progress_signal.connect(self.progress_bar.setValue)
        self.extractor_stop: callable = self.extractor.stop_callback
        self.extractor.start()

    def stop(self):
        if self.extractor:
            self.extractor_stop()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SemantixWidget()
    window.show()

    sys.exit(app.exec())
