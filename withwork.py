from PyQt6.QtWidgets import *
from PyQt6.QtCore import Qt, QDate
from Diplom.src.database import DB_Settings
from datetime import date, timedelta
from datetime import datetime, timedelta, time
import calendar
from datetime import timedelta, time
import random


class MainWindow(QMainWindow):
    def __init__(self, user_data=None):  # Изменяем параметр на user_data
        super().__init__()
        # Устанавливаем значения по умолчанию
        self.user_data = user_data or {
            'id': 0,
            'username': 'Гость',
            'full_name': 'Иванов И.И.',
            'role': 'student'
        }
        self.setup_ui()

    def load_workload_for_group(self, conn, group_name):
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM workload WHERE group_name = %s", (group_name,))
            columns = [desc[0] for desc in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return results

    def generate_schedules_for_all_groups(self, start_date):
        conn = DB_Settings.get_connection()
        cursor = conn.cursor()

        try:
            # Запрашиваем список всех групп из таблицы workload или groups
            cursor.execute("SELECT DISTINCT group_name FROM workload")
            groups = [row[0] for row in cursor.fetchall()]

            all_schedules = []

            for group_name in groups:
                print(f"Генерация расписания для группы: {group_name}")
                schedule = self.generate_week_schedule_balanced(group_name, start_date)
                all_schedules.append({
                    'group_name': group_name,
                    'schedule': schedule
                })
            QMessageBox.information(self, "Успешно!", f"Расписание сгенерировано успешно")
            return all_schedules

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сгенерировать расписание: {str(e)}")
            conn.rollback()
            return []

        finally:
            conn.commit()
            cursor.close()

    def generate_week_schedule_balanced(self, group_name, start_date):
        conn = DB_Settings.get_connection()
        cursor = conn.cursor()

        workload = self.load_workload_for_group(conn, group_name)

        subject_hours = {record['index_code']: float(record['total']) for record in workload}
        subject_teachers = {record['index_code']: record['teacher'] for record in workload}

        total_week_hours = 0
        max_week_hours = 40
        max_hours_per_day = 10
        max_pairs_per_day = 5
        week_schedule = []
        recent_subjects = set()  # Для исключения повторов из предыдущего дня

        for i in range(6):  # Понедельник — Суббота
            current_date = start_date + timedelta(days=i)
            pairs_scheduled = 0
            hours_scheduled_today = 0
            used_today = set()

            # Получаем список предметов с оставшимися часами
            available_subjects = [subj for subj in subject_hours if subject_hours[subj] > 0]
            # Исключаем предметы, которые были накануне (по возможности)
            available_subjects = [s for s in available_subjects if s not in recent_subjects] or list(
                subject_hours.keys())
            # Сортируем по убыванию оставшихся часов, но с лёгкой случайностью
            random.shuffle(available_subjects)
            available_subjects.sort(key=lambda s: subject_hours[s], reverse=True)

            for subject in available_subjects:
                if pairs_scheduled >= max_pairs_per_day or hours_scheduled_today >= max_hours_per_day:
                    break
                if subject_hours[subject] <= 0:
                    continue

                hours_to_schedule = min(2, subject_hours[subject], max_hours_per_day - hours_scheduled_today)

                if total_week_hours + hours_to_schedule > max_week_hours:
                    break

                start_time = time(8 + pairs_scheduled * 2, 0)

                schedule_entry = {
                    'group_name': group_name,
                    'teacher': subject_teachers[subject],
                    'subject': subject,
                    'date': current_date,
                    'start_time': start_time,
                    'duration_hours': hours_to_schedule
                }

                week_schedule.append(schedule_entry)

                # Вставляем запись в базу данных
                cursor.execute("""
                    INSERT INTO schedule (group_name, teacher, subject, date, start_time, duration_hours)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    group_name,
                    subject_teachers[subject],
                    subject,
                    current_date,
                    start_time,
                    hours_to_schedule
                ))

                subject_hours[subject] -= hours_to_schedule
                total_week_hours += hours_to_schedule
                hours_scheduled_today += hours_to_schedule
                pairs_scheduled += 1
                used_today.add(subject)

            # На следующий день постараемся не повторять сегодняшние предметы
            recent_subjects = used_today.copy()

        conn.commit()
        cursor.close()
        return week_schedule

    def load_groups_from_db(self):
        try:
            conn = DB_Settings.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT DISTINCT group_name FROM workload")
                groups = [row[0] for row in cursor.fetchall()]
                return groups
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить группы: {str(e)}")
            return []

    def show_schedule_in_table(self, schedule):
        dialog = QDialog(self)
        dialog.setWindowTitle("Сгенерированное расписание")
        layout = QVBoxLayout(dialog)

        # Подготовка дней недели и временных слотов
        days_ru = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']

        # Временные слоты по 2 академических часа
        time_slots = [
            "08:00 – 10:00",
            "10:00 – 12:00",
            "12:30 – 14:30",
            "14:30 – 16:30",
            "16:30 – 18:30"
        ]

        # Создание таблицы
        table = QTableWidget()
        table.setColumnCount(len(days_ru))
        table.setRowCount(len(time_slots))
        table.setHorizontalHeaderLabels(days_ru)
        table.setVerticalHeaderLabels(time_slots)

        # Заполнение таблицы
        for pair in schedule:
            day_of_week = pair['date'].weekday()  # 0=Пн, ..., 5=Сб
            start_hour = pair['start_time'].hour
            duration = pair['duration_hours']

            # Определение индекса временного слота
            time_index = -1
            for i, slot in enumerate(time_slots):
                slot_start = int(slot.split(" – ")[0].split(":")[0])
                if start_hour == slot_start:
                    time_index = i
                    break

            if time_index != -1:
                subject_teacher = f"{pair['subject']}\n{pair['teacher']}"
                item = QTableWidgetItem(subject_teacher)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(time_index, day_of_week, item)

        # Настройки внешнего вида
        table.resizeColumnsToContents()
        table.resizeRowsToContents()
        table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(table)

        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.exec()

    def show_generate_schedule_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Сгенерировать расписание")

        form = QFormLayout(dialog)

        group_combo = QComboBox()
        group_combo.addItems(self.load_groups_from_db())  # можно загрузить из БД

        date_edit = QDateEdit()
        date_edit.setDate(QDate.currentDate())

        form.addRow("Группа:", group_combo)
        form.addRow("Дата начала недели:", date_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            group_name = group_combo.currentText()
            start_date = date_edit.date().toPyDate()

            conn = DB_Settings.get_connection()
            schedule = self.generate_week_schedule_balanced(group_name, start_date)
            self.show_schedule_in_table(schedule)

    def setup_ui(self):
        self.setWindowTitle(f"SmartУчеба - {self.user_data['full_name']} ({self.user_data['role'].capitalize()})")
        self.setFixedSize(1200, 800)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.layout = QHBoxLayout(central_widget)

        self.setup_sidebar()
        self.workspace = QStackedWidget()
        self.layout.addWidget(self.workspace, stretch=5)

        if self.user_data['role'] == "admin":
            self.setup_admin_workspace()
        elif self.user_data['role'] == "teacher":
            self.setup_teacher_workspace()
        else:
            self.setup_student_workspace()

        self.setup_styles()

    def load_data(self, data):
        self.QTableWidget.setRowCount(len(data))
        self.QTableWidget.setColumnCount(len(data[0]) if data else 0)

        for RowIndex, rows in enumerate(data):
            for Colindex, item in enumerate(rows):
                self.QTableWidget.setItern(RowIndex, Colindex, QTableWidgetItem(str(item)))

    def setup_sidebar(self):
        sidebar = QFrame()
        sidebar.setFrameShape(QFrame.Shape.StyledPanel)
        sidebar_layout = QVBoxLayout(sidebar)

        # Используем реальные данные пользователя
        user_info = QLabel(f"{self.user_data['full_name']}\n{self.user_data['role'].capitalize()}")
        user_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_layout.addWidget(user_info)

        buttons = [
            ("Расписание", self.show_schedule),
            ("Нагрузка", self.show_workload),
            ("Отчеты", self.show_reports),
            ("Настройки", self.show_settings)
        ]

        for text, handler in buttons:
            btn = QPushButton(text)
            btn.clicked.connect(handler)
            sidebar_layout.addWidget(btn)

        # Кнопка выхода
        sidebar_layout.addStretch()
        logout_btn = QPushButton("Выход")
        logout_btn.clicked.connect(self.close)
        sidebar_layout.addWidget(logout_btn)

        self.layout.addWidget(sidebar, stretch=1)

    def get_next_monday(self):
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7
        return today + timedelta(days=days_until_monday)

    def setup_admin_workspace(self):  #
        tabs = QTabWidget()

        # Вкладка дашборда
        dashboard_tab = QWidget()
        grid = QGridLayout(dashboard_tab)

        # Heatmap аудиторий
        grid.addWidget(QLabel("Загрузка аудиторий"), 0, 0)
        self.room_heatmap = QLabel("График будет здесь")
        grid.addWidget(self.room_heatmap, 1, 0)

        # Список конфликтов
        grid.addWidget(QLabel("Текущие конфликты"), 0, 1)
        self.conflict_list = QListWidget()
        self.conflict_list.addItems(["Конфликт 1", "Конфликт 2"])
        grid.addWidget(self.conflict_list, 1, 1)

        # Кнопки управления
        btn_generate_balanced = QPushButton("Сгенерировать расписание (баланс)")

        btn_generate_balanced.clicked.connect(
            lambda: self.generate_schedules_for_all_groups(start_date=self.get_next_monday()))
        grid.addWidget(btn_generate_balanced, 3, 0, 1, 2)

        tabs.addTab(dashboard_tab, "Дашборд")

        # Новая вкладка для управления заявками
        requests_tab = QWidget()
        requests_layout = QVBoxLayout(requests_tab)

        self.requests_table = QTableWidget()
        self.requests_table.setColumnCount(6)
        self.requests_table.setHorizontalHeaderLabels(
            ["ID", "Преподаватель", "Дата", "Тип изменения", "Причина", "Статус"])
        self.requests_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        requests_layout.addWidget(self.requests_table)

        # Кнопки для работы с заявками
        btn_refresh = QPushButton("Обновить список")
        btn_refresh.clicked.connect(self.load_requests)
        requests_layout.addWidget(btn_refresh)

        btn_approve = QPushButton("Утвердить выбранное")
        btn_approve.clicked.connect(self.approve_request)
        requests_layout.addWidget(btn_approve)

        btn_reject = QPushButton("Отклонить выбранное")
        btn_reject.clicked.connect(self.reject_request)
        requests_layout.addWidget(btn_reject)

        tabs.addTab(requests_tab, "Заявки на изменения")
        self.workspace.addWidget(tabs)
        self.load_requests()



    def setup_teacher_workspace(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        # Календарь
        self.calendar = QCalendarWidget()
        self.calendar.clicked.connect(self.load_lessons_for_date)  # подключаем обработчик клика
        layout.addWidget(self.calendar)

        # Таблица занятий
        self.lessons_table = QTableWidget()
        self.lessons_table.setColumnCount(4)
        self.lessons_table.setHorizontalHeaderLabels(["Дата", "Дисциплина", "Аудитория", "Тип"])
        layout.addWidget(self.lessons_table)

        # Кнопка запроса
        btn_request = QPushButton("Запрос изменения")
        btn_request.clicked.connect(self.show_request_dialog)
        layout.addWidget(btn_request)

        self.workspace.addWidget(container)

        # Загрузка на текущую дату при запуске
        self.load_lessons_for_date(self.calendar.selectedDate())

    def load_lessons_for_date(self, qdate: QDate):
        selected_date = qdate.toString("yyyy-MM-dd")

        try:
            conn = DB_Settings.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT subject, start_time, duration_hours 
                    FROM schedule
                    INNER JOIN user ON schedule.teacher = user.UserFullName
                    WHERE user.UserName = %s AND date = %s
                    ORDER BY start_time
                """, (self.user_data['username'], selected_date))

                results = cursor.fetchall()

                self.lessons_table.setRowCount(len(results))
                for i, row in enumerate(results):
                    subject, start_time, duration = row
                    self.lessons_table.setItem(i, 0, QTableWidgetItem(selected_date))  # Дата
                    self.lessons_table.setItem(i, 1, QTableWidgetItem(subject))  # Дисциплина
                    self.lessons_table.setItem(i, 2, QTableWidgetItem(str(start_time)))  # Аудитория (временно)
                    self.lessons_table.setItem(i, 3, QTableWidgetItem(f"{duration} ч"))  # Тип (временно)
        except Exception as e:
            print("Ошибка при загрузке расписания:", e)

    # В "Тип" выводим длительность

    def load_requests(self):
        """Загружает список заявок на изменения"""
        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT r.RequestId, u.UserFullName, r.RequestDate, 
                               r.ChangeType, r.Reason, r.Status
                        FROM ScheduleChangeRequests r
                        JOIN user u ON r.TeacherId = u.UserId
                        ORDER BY r.RequestDate DESC
                    """)
                    requests = cursor.fetchall()

                    self.requests_table.setRowCount(len(requests))
                    for row, (req_id, teacher, date, change_type, reason, status) in enumerate(requests):
                        self.requests_table.setItem(row, 0, QTableWidgetItem(str(req_id)))
                        self.requests_table.setItem(row, 1, QTableWidgetItem(teacher))
                        self.requests_table.setItem(row, 2, QTableWidgetItem(str(date)))
                        self.requests_table.setItem(row, 3, QTableWidgetItem(change_type))
                        self.requests_table.setItem(row, 4, QTableWidgetItem(reason))
                        self.requests_table.setItem(row, 5, QTableWidgetItem(status))

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить заявки: {str(e)}")

    def approve_request(self):
        """Утверждает выбранную заявку"""
        selected = self.requests_table.currentRow()
        if selected == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите заявку для утверждения")
            return

        request_id = int(self.requests_table.item(selected, 0).text())

        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Получаем данные заявки
                    cursor.execute("""
                        SELECT TeacherId, ScheduleId, NewDate, NewClassroomId, ChangeType
                        FROM ScheduleChangeRequests
                        WHERE RequestId = %s
                    """, (request_id,))
                    request_data = cursor.fetchone()

                    if not request_data:
                        QMessageBox.warning(self, "Ошибка", "Заявка не найдена")
                        return

                    teacher_id, schedule_id, new_date, new_classroom, change_type = request_data

                    # Обновляем расписание
                    if change_type == "Перенос":
                        cursor.execute("""
                            UPDATE Schedule 
                            SET DayOfWeek = %s, ClassroomId = %s
                            WHERE ScheduleId = %s
                        """, (self.get_day_of_week(new_date), new_classroom, schedule_id))
                    elif change_type == "Отмена":
                        cursor.execute("""
                            DELETE FROM Schedule WHERE ScheduleId = %s
                        """, (schedule_id,))

                    # Обновляем статус заявки
                    cursor.execute("""
                        UPDATE ScheduleChangeRequests
                        SET Status = 'Утверждено', ProcessedBy = %s, ProcessedDate = NOW()
                        WHERE RequestId = %s
                    """, (self.user_data['id'], request_id))

                    conn.commit()
                    QMessageBox.information(self, "Успех", "Заявка утверждена и изменения внесены")
                    self.load_requests()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось утвердить заявку: {str(e)}")

    def reject_request(self):
        """Отклоняет выбранную заявку"""
        selected = self.requests_table.currentRow()
        if selected == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите заявку для отклонения")
            return

        request_id = int(self.requests_table.item(selected, 0).text())

        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Обновляем статус заявки
                    cursor.execute("""
                        UPDATE ScheduleChangeRequests
                        SET Status = 'Отклонено', ProcessedBy = %s, ProcessedDate = NOW()
                        WHERE RequestId = %s
                    """, (self.user_data['id'], request_id))

                    conn.commit()
                    QMessageBox.information(self, "Успех", "Заявка отклонена")
                    self.load_requests()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось отклонить заявку: {str(e)}")

    def get_day_of_week(self, date):
        """Возвращает день недели для даты"""
        days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
        return days[date.weekday()]  # предполагая, что date - это datetime.date

    def show_request_dialog(self):
        """Показывает диалог создания заявки на изменение"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Запрос изменения расписания")
        dialog.resize(500, 300)

        form = QFormLayout(dialog)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())

        self.classroom_combo = QComboBox()
        self.load_classrooms()

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Перенос", "Отмена"])

        self.reason_edit = QTextEdit()

        form.addRow("Дата изменения:", self.date_edit)
        form.addRow("Новая аудитория:", self.classroom_combo)
        form.addRow("Тип изменения:", self.type_combo)
        form.addRow("Причина:", self.reason_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(lambda: self.submit_request(dialog))
        buttons.rejected.connect(dialog.reject)

        form.addRow(buttons)

        dialog.exec()

    from datetime import time, timedelta

    def load_schedule_from_db(self, group_name):
        conn = DB_Settings.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT date, start_time, subject 
                FROM schedule 
                WHERE group_name = %s 
                ORDER BY date, start_time
            """, (group_name,))
            rows = cursor.fetchall()

            # Структура: день недели -> номер пары -> предмет
            schedule_data = [["" for _ in range(5)] for _ in range(6)]
            day_map = {
                0: 0,  # Пн
                1: 1,  # Вт
                2: 2,  # Ср
                3: 3,  # Чт
                4: 4,  # Пт
                5: 5,
            }

            for record in rows:
                date_obj, start_time, subject = record
                weekday = date_obj.weekday()  # 0=Пн ... 5=Сб
                if weekday >= 5:
                    continue

                # Безопасное получение часа
                hour = 8  # значение по умолчанию

                if isinstance(start_time, time):
                    hour = start_time.hour
                elif isinstance(start_time, timedelta):
                    # Преобразуем timedelta в часы
                    total_seconds = int(start_time.total_seconds())
                    hour = total_seconds // 3600  # 3600 секунд в часе
                else:
                    hour = 8  # дефолтное время начала занятий

                pair_number = (hour - 8) // 2  # 8-10 → 0, 10-12 → 1 и т.д.
                col = day_map[weekday]
                row = pair_number

                if 0 <= row < 6 and 0 <= col < 5:
                    schedule_data[row][col] = subject

            return schedule_data

        except Exception as e:
            print("Ошибка при загрузке расписания из БД:", e)
            return [["" for _ in range(5)] for _ in range(6)]

        finally:
            cursor.close()

    def setup_student_workspace(self):
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Панель фильтров
        filter_panel = QWidget()
        filter_layout = QHBoxLayout(filter_panel)
        filter_layout.addWidget(QLabel("Группа:"))
        self.group_combo = QComboBox()
        self.group_combo.addItems(self.load_groups_from_db())
        filter_layout.addWidget(self.group_combo)
        splitter.addWidget(filter_panel)

        # Таблица расписания
        self.schedule_table = QTableWidget(6, 5)  # 6 пар, 5 дней
        self.schedule_table.setHorizontalHeaderLabels(["Пн", "Вт", "Ср", "Чт", "Пт"])
        self.schedule_table.setVerticalHeaderLabels([f"{i + 1}. 9:00-10:30" for i in range(6)])

        # Добавляем таблицу в интерфейс
        splitter.addWidget(self.schedule_table)
        self.workspace.addWidget(splitter)

        # Загружаем расписание по умолчанию
        self.update_schedule("Бизнес-101")  # можно заменить на первую группу из combo

        # Подключаем обработчик изменения группы
        self.group_combo.currentIndexChanged.connect(self.on_group_changed)
        self.on_group_changed()  # Загрузить расписание сразу при запуске

    def on_group_changed(self):
        selected_group = self.group_combo.currentText()
        self.update_schedule(selected_group)

    def update_schedule(self, group_name):
        schedule_data = self.load_schedule_from_db(group_name)

        self.schedule_table.setRowCount(len(schedule_data))
        for row in range(len(schedule_data)):
            for col in range(len(schedule_data[row])):
                item_text = schedule_data[row][col]
                self.schedule_table.setItem(row, col, QTableWidgetItem(item_text))

    def on_group_changed(self):
        selected_group = self.group_combo.currentText()
        self.update_schedule(selected_group)

    def setup_styles(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f5f5;
                font-family: Arial;
            }
            QPushButton {
                padding: 8px;
                background: #3f51b5;
                color: white;
                border: none;
                border-radius: 4px;
                min-width: 100px;
            }
            QPushButton:hover {
                background: #5c6bc0;
            }
            QTableWidget {
                gridline-color: #e0e0e0;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #e3f2fd;
                padding: 5px;
                border: none;
            }
            QFrame {
                background: white;
                border-right: 1px solid #ddd;
            }
            QListWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
            }
        """)

    def show_schedule(self):
        QMessageBox.information(self, "Навигация", "Вы уже находитесь в разделе расписания")

    def show_workload(self):
        """Отображение нагрузки пользователя"""
        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    if self.user_data['role'] == 'teacher':
                        # Для преподавателя: показываем его дисциплины по группам
                        cursor.execute("""
                            SELECT 
                                index_code AS SubjectName, 
                                group_name AS GroupName, 
                                total AS Hours
                            FROM workload inner join user on workload.teacher = user.UserFullName
                            WHERE user.UserName = %s
                        """, (self.user_data['username'],))
                        workload_data = cursor.fetchall()

                        dialog = QDialog(self)
                        dialog.setWindowTitle(f"Нагрузка преподавателя {self.user_data['full_name']}")
                        dialog.resize(800, 400)
                        layout = QVBoxLayout(dialog)

                        # Таблица с нагрузкой
                        table = QTableWidget()
                        table.setColumnCount(3)
                        table.setHorizontalHeaderLabels(["Дисциплина", "Группа", "Часы"])
                        table.setRowCount(len(workload_data))

                        total_hours = 0
                        for row, (subject, group, hours) in enumerate(workload_data):
                            table.setItem(row, 0, QTableWidgetItem(subject))
                            table.setItem(row, 1, QTableWidgetItem(group))
                            table.setItem(row, 2, QTableWidgetItem(str(hours)))
                            total_hours += hours

                        layout.addWidget(table)

                        # Суммарная нагрузка
                        lbl_total = QLabel(f"Общая нагрузка: {total_hours} часов")
                        layout.addWidget(lbl_total)

                        # Кнопка закрытия
                        btn_close = QPushButton("Закрыть")
                        btn_close.clicked.connect(dialog.close)
                        layout.addWidget(btn_close)

                        dialog.exec()

                    elif self.user_data['role'] == 'admin':
                        # Для администратора: сводная нагрузка по всем преподавателям
                        cursor.execute("""
                            SELECT 
                                teacher AS TeacherName,
                                COUNT(*) AS SubjectsCount,
                                SUM(hours_1_semester) AS TotalHoursSem1,
                                SUM(hours_2_semester) AS TotalHoursSem2,
                                SUM(total) AS TotalHours
                            FROM workload
                            GROUP BY teacher
                            ORDER BY TotalHours DESC
                        """)
                        workload_data = cursor.fetchall()

                        dialog = QDialog(self)
                        dialog.setWindowTitle("Нагрузка преподавателей")
                        dialog.resize(900, 400)
                        layout = QVBoxLayout(dialog)

                        table = QTableWidget()
                        table.setColumnCount(5)
                        table.setHorizontalHeaderLabels([
                            "Преподаватель",
                            "Кол-во дисциплин",
                            "1 семестр (часов)",
                            "2 семестр (часов)",
                            "Всего часов"
                        ])
                        table.setRowCount(len(workload_data))

                        for row, (teacher, subjects, sem1, sem2, total) in enumerate(workload_data):
                            table.setItem(row, 0, QTableWidgetItem(teacher or "-"))
                            table.setItem(row, 1, QTableWidgetItem(str(subjects)))
                            table.setItem(row, 2, QTableWidgetItem(str(sem1)))
                            table.setItem(row, 3, QTableWidgetItem(str(sem2)))
                            table.setItem(row, 4, QTableWidgetItem(str(total)))

                        layout.addWidget(table)

                        # Кнопка закрытия
                        btn_close = QPushButton("Закрыть")
                        btn_close.clicked.connect(dialog.close)
                        layout.addWidget(btn_close)

                        dialog.exec()

                    else:
                        QMessageBox.information(self, "Нагрузка",
                                                "Функция доступна только преподавателям и администраторам")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить данные о нагрузке: {str(e)}")

    def show_reports(self):
        """Отображение отчетов в зависимости от роли пользователя"""
        try:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Отчеты - {self.user_data['full_name']}")
            dialog.resize(1000, 700)

            layout = QVBoxLayout(dialog)
            tab_widget = QTabWidget()

            # 1. Общие отчеты (для всех пользователей)
            self.add_general_reports_tab(tab_widget)

            # 2. Отчеты для преподавателей
            if self.user_data['role'] == 'teacher':
                self.add_teacher_reports_tab(tab_widget)

            # 3. Отчеты для администраторов
            if self.user_data['role'] == 'admin':
                self.add_admin_reports_tab(tab_widget)

            layout.addWidget(tab_widget)
            dialog.exec()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сформировать отчеты: {str(e)}")

    def add_general_reports_tab(self, tab_widget):
        """Общие отчеты доступные всем пользователям"""
        report_widget = QWidget()
        layout = QVBoxLayout(report_widget)

        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Отчет: количество групп
                    cursor.execute("SELECT COUNT(DISTINCT group_name) FROM workload")
                    total_groups = cursor.fetchone()[0]

                    # Отчет: количество предметов
                    cursor.execute("SELECT COUNT(DISTINCT index_code) FROM workload")
                    total_subjects = cursor.fetchone()[0]

                    # Отчет: количество преподавателей
                    cursor.execute("SELECT COUNT(DISTINCT teacher) FROM workload")
                    total_teachers = cursor.fetchone()[0]

                    # Отчет: количество студентов
                    cursor.execute("SELECT COUNT(*) FROM user WHERE UserPositionId = 2")
                    total_students = cursor.fetchone()[0]

                    # Отображаем данные как текст
                    stats_label = QLabel(f"""
                        <h3>📊 Общая статистика:</h3>
                        <ul>
                            <li>👥 Всего групп: <b>{total_groups}</b></li>
                            <li>📘 Всего предметов: <b>{total_subjects}</b></li>
                            <li>👨‍🏫 Всего преподавателей: <b>{total_teachers}</b></li>
                            <li>🎓 Всего студентов: <b>{total_students}</b></li>
                        </ul>
                    """)
                    layout.addWidget(stats_label)

        except Exception as e:
            QMessageBox.critical(report_widget, "Ошибка", f"Не удалось загрузить общую статистику: {str(e)}")

        layout.addStretch()
        report_widget.setLayout(layout)
        tab_widget.addTab(report_widget, "📊 Статистика")

    def add_teacher_reports_tab(self, tab_widget):
        """Отчеты для преподавателей"""

        # --- 1. Отчет по нагрузке преподавателя ---
        workload_widget = QWidget()
        workload_layout = QVBoxLayout(workload_widget)

        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            index_code AS SubjectCode,
                            group_name AS GroupName,
                            hours_1_semester AS Semester1Hours,
                            hours_2_semester AS Semester2Hours,
                            total AS TotalHours
                        FROM workload
                        INNER JOIN user ON user.UserFullName = workload.teacher
                        WHERE UserName = %s
                        ORDER BY group_name
                    """, (self.user_data['full_name'],))

                    workload_data = cursor.fetchall()

                    workload_table = QTableWidget()
                    workload_table.setColumnCount(5)
                    workload_table.setHorizontalHeaderLabels([
                        "Предмет",
                        "Группа",
                        "Часов семестр 1",
                        "Часов семестр 2",
                        "Всего часов"
                    ])
                    workload_table.setRowCount(len(workload_data))

                    total_hours = 0
                    for row, (subject, group, sem1, sem2, total) in enumerate(workload_data):
                        workload_table.setItem(row, 0, QTableWidgetItem(subject))
                        workload_table.setItem(row, 1, QTableWidgetItem(group))
                        workload_table.setItem(row, 2, QTableWidgetItem(str(sem1)))
                        workload_table.setItem(row, 3, QTableWidgetItem(str(sem2)))
                        workload_table.setItem(row, 4, QTableWidgetItem(str(total)))
                        total_hours += total

                    workload_layout.addWidget(workload_table)

                    lbl_total = QLabel(f"Общая нагрузка: {total_hours} часов")
                    lbl_total.setStyleSheet("font-weight: bold; font-size: 12pt;")
                    workload_layout.addWidget(lbl_total)

        except Exception as e:
            QMessageBox.critical(workload_widget, "Ошибка", f"Не удалось загрузить отчёт по нагрузке: {str(e)}")

        tab_widget.addTab(workload_widget, "Моя нагрузка")

        # --- 2. Мои группы ---
        groups_widget = QWidget()
        groups_layout = QVBoxLayout(groups_widget)

        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT DISTINCT group_name
                        FROM workload inner join user on workload.teacher = user.UserFullName
                            WHERE user.UserName = %s
                    """, (self.user_data['full_name'],))

                    groups_data = cursor.fetchall()

                    groups_table = QTableWidget()
                    groups_table.setColumnCount(1)
                    groups_table.setHorizontalHeaderLabels(["Группа"])
                    groups_table.setRowCount(len(groups_data))

                    for row, (group,) in enumerate(groups_data):
                        groups_table.setItem(row, 0, QTableWidgetItem(group))

                    groups_layout.addWidget(groups_table)

        except Exception as e:
            QMessageBox.critical(groups_widget, "Ошибка", f"Не удалось загрузить список групп: {str(e)}")

        tab_widget.addTab(groups_widget, "Мои группы")

        # --- 3. Мои предметы ---
        subjects_widget = QWidget()
        subjects_layout = QVBoxLayout(subjects_widget)

        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT DISTINCT index_code
                        FROM workload inner join user on workload.teacher = user.UserFullName
                            WHERE user.UserName = %s
                    """, (self.user_data['full_name'],))

                    subjects_data = cursor.fetchall()

                    subjects_table = QTableWidget()
                    subjects_table.setColumnCount(1)
                    subjects_table.setHorizontalHeaderLabels(["Предмет"])
                    subjects_table.setRowCount(len(subjects_data))

                    for row, (subject,) in enumerate(subjects_data):
                        subjects_table.setItem(row, 0, QTableWidgetItem(subject))

                    subjects_layout.addWidget(subjects_table)

        except Exception as e:
            QMessageBox.critical(subjects_widget, "Ошибка", f"Не удалось загрузить список предметов: {str(e)}")

        tab_widget.addTab(subjects_widget, "Мои предметы")

    def add_admin_reports_tab(self, tab_widget):
        self.add_teacher_workload_report(tab_widget)  # Твой текущий отчет о нагрузке преподавателей
        self.add_group_report(tab_widget)
        self.add_subjects_report(tab_widget)
        self.add_users_list_report(tab_widget)

    def add_subjects_report(self, tab_widget):
        subject_widget = QWidget()
        layout = QVBoxLayout(subject_widget)

        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            index_code AS SubjectCode,
                            teacher AS TeacherName,
                            group_name AS GroupName,
                            total AS TotalHours
                        FROM workload
                        ORDER BY SubjectCode, TeacherName
                    """)
                    rows = cursor.fetchall()

                    table = QTableWidget()
                    table.setColumnCount(4)
                    table.setHorizontalHeaderLabels(["Предмет", "Преподаватель", "Группа", "Часов"])
                    table.setRowCount(len(rows))

                    for row_index, (subject, teacher, group, hours) in enumerate(rows):
                        table.setItem(row_index, 0, QTableWidgetItem(subject or "-"))
                        table.setItem(row_index, 1, QTableWidgetItem(teacher or "-"))
                        table.setItem(row_index, 2, QTableWidgetItem(group or "-"))
                        table.setItem(row_index, 3, QTableWidgetItem(str(hours)))

                    layout.addWidget(table)

                    btn_export = QPushButton("Экспорт в Excel")
                    btn_export.clicked.connect(lambda: self.export_to_excel(
                        rows,
                        ["Предмет", "Преподаватель", "Группа", "Часов"],
                        "subjects_report"
                    ))
                    layout.addWidget(btn_export)

        except Exception as e:
            QMessageBox.critical(subject_widget, "Ошибка", f"Не удалось загрузить список предметов: {str(e)}")

        tab_widget.addTab(subject_widget, "Предметы")

    def add_group_report(self, tab_widget):
        group_widget = QWidget()
        layout = QVBoxLayout(group_widget)

        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            g.group_name AS GroupName,

                            COUNT(*) AS StudentCount
                        FROM workload g
                        LEFT JOIN user u ON g.teacher = u.UserFullName AND u.UserPositionId = 2
                        GROUP BY g.group_name
                        ORDER BY GroupName;
                    """)
                    rows = cursor.fetchall()

                    table = QTableWidget()
                    table.setColumnCount(2)
                    table.setHorizontalHeaderLabels(["Группа", "Преподователей"])
                    table.setRowCount(len(rows))

                    for row_index, (group, count) in enumerate(rows):
                        table.setItem(row_index, 0, QTableWidgetItem(group))
                        table.setItem(row_index, 1, QTableWidgetItem(str(count)))

                    layout.addWidget(table)

                    btn_export = QPushButton("Экспорт в Excel")
                    btn_export.clicked.connect(lambda: self.export_to_excel(
                        rows,
                        ["Группа", "Специализация", "Студентов"],
                        "group_report"
                    ))
                    layout.addWidget(btn_export)

        except Exception as e:
            QMessageBox.critical(group_widget, "Ошибка", f"Не удалось загрузить данные: {str(e)}")

        tab_widget.addTab(group_widget, "Группы")

    def add_users_list_report(self, tab_widget):
        users_widget = QWidget()
        layout = QVBoxLayout(users_widget)

        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT UserName, UserFullName, Position.PositionName, IFNULL(group_name, '-')
                        FROM user INNER JOIN Position on user.UserPositionId = Position.PositionId
                        LEFT JOIN workload ON user.UserFullName = workload.teacher
                    """)
                    rows = cursor.fetchall()

                    table = QTableWidget()
                    table.setColumnCount(4)
                    table.setHorizontalHeaderLabels(["Логин", "ФИО", "Роль", "Группа"])
                    table.setRowCount(len(rows))

                    for row_index, (username, fullname, role, group) in enumerate(rows):
                        table.setItem(row_index, 0, QTableWidgetItem(username or "-"))
                        table.setItem(row_index, 1, QTableWidgetItem(fullname or "-"))
                        table.setItem(row_index, 2, QTableWidgetItem(role or "-"))
                        table.setItem(row_index, 3, QTableWidgetItem(group or "-"))

                    layout.addWidget(table)

                    btn_export = QPushButton("Экспорт в Excel")
                    btn_export.clicked.connect(lambda: self.export_to_excel(
                        rows,
                        ["Логин", "ФИО", "Роль", "Группа"],
                        "users_report"
                    ))
                    layout.addWidget(btn_export)

        except Exception as e:
            QMessageBox.critical(users_widget, "Ошибка", f"Не удалось загрузить список пользователей: {str(e)}")

        tab_widget.addTab(users_widget, "Пользователи")

    def add_teacher_workload_report(self, tab_widget):
        # Вкладка: Нагрузка преподавателей
        teacher_workload_widget = QWidget()
        layout = QVBoxLayout(teacher_workload_widget)

        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            teacher AS TeacherName,
                            COUNT(*) AS SubjectsCount,
                            SUM(hours_1_semester) AS TotalHoursSem1,
                            SUM(hours_2_semester) AS TotalHoursSem2,
                            SUM(total) AS TotalHours
                        FROM workload
                        GROUP BY teacher
                        ORDER BY TotalHours DESC;
                    """)
                    rows = cursor.fetchall()

                    table = QTableWidget()
                    table.setColumnCount(5)
                    table.setHorizontalHeaderLabels([
                        "Преподаватель",
                        "Кол-во дисциплин",
                        "Часов семестр 1",
                        "Часов семестр 2",
                        "Всего часов"
                    ])
                    table.setRowCount(len(rows))

                    for row_index, (name, subjects, sem1, sem2, total) in enumerate(rows):
                        table.setItem(row_index, 0, QTableWidgetItem(name or "-"))
                        table.setItem(row_index, 1, QTableWidgetItem(str(subjects)))
                        table.setItem(row_index, 2, QTableWidgetItem(str(sem1)))
                        table.setItem(row_index, 3, QTableWidgetItem(str(sem2)))
                        table.setItem(row_index, 4, QTableWidgetItem(str(total)))

                    layout.addWidget(table)

                    # Кнопка экспорта в Excel
                    btn_export = QPushButton("Экспорт в Excel")
                    btn_export.clicked.connect(lambda: self.export_to_excel(
                        rows,
                        ["Преподаватель", "Кол-во дисциплин", "Семестр 1", "Семестр 2", "Всего часов"],
                        "teacher_load_report"
                    ))
                    layout.addWidget(btn_export)

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить данные: {str(e)}")
            tab_widget.addTab(self, "Группы")

    def export_to_excel(self, data, headers, report_name):
        """Экспорт данных в Excel"""
        try:
            from openpyxl import Workbook
            from datetime import datetime
            import os

            wb = Workbook()
            ws = wb.active
            ws.title = "Отчет"

            # Заголовки
            ws.append(headers)

            # Данные
            for row in data:
                ws.append(row)

            # Автоматическая ширина столбцов
            for col in ws.columns:
                max_length = 0
                column = col[0].column_letter
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = (max_length + 2) * 1.2
                ws.column_dimensions[column].width = adjusted_width

            # Сохраняем файл
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = f"{report_name}_{timestamp}.xlsx"
            wb.save(file_path)

            QMessageBox.information(self, "Экспорт",
                                    f"Отчет успешно сохранен:\n{os.path.abspath(file_path)}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось экспортировать данные: {str(e)}")

    def show_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Настройки")
        dialog.resize(500, 300)

        layout = QVBoxLayout(dialog)
        tab_widget = QTabWidget()

        # --- Вкладка: Пользователь ---
        user_tab = QWidget()
        user_layout = QFormLayout(user_tab)

        self.username_input = QLineEdit(self.user_data['username'])
        self.fullname_input = QLineEdit(self.user_data['full_name'])

        user_layout.addRow("Имя пользователя:", self.username_input)
        user_layout.addRow("Полное имя:", self.fullname_input)

        save_user_btn = QPushButton("Сохранить данные пользователя")
        save_user_btn.clicked.connect(lambda: self.save_user_settings(dialog))
        user_layout.addWidget(save_user_btn)

        tab_widget.addTab(user_tab, "Пользователь")

        # --- Вкладка: База данных (только для админа) ---
        if self.user_data['role'] == 'admin':
            db_tab = QWidget()
            db_layout = QFormLayout(db_tab)

            self.db_host_input = QLineEdit(DB_Settings.DB_CONFIG['host'])
            self.db_port_input = QLineEdit(str(DB_Settings.DB_CONFIG['port']))
            self.db_user_input = QLineEdit(DB_Settings.DB_CONFIG['user'])
            self.db_pass_input = QLineEdit(DB_Settings.DB_CONFIG['password'])
            self.db_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.db_name_input = QLineEdit(DB_Settings.DB_CONFIG['database'])

            db_layout.addRow("Хост:", self.db_host_input)
            db_layout.addRow("Порт:", self.db_port_input)
            db_layout.addRow("Пользователь:", self.db_user_input)
            db_layout.addRow("Пароль:", self.db_pass_input)
            db_layout.addRow("База данных:", self.db_name_input)

            save_db_btn = QPushButton("Сохранить настройки БД")
            save_db_btn.clicked.connect(self.save_db_settings)
            db_layout.addWidget(save_db_btn)

            tab_widget.addTab(db_tab, "База данных")

        layout.addWidget(tab_widget)

        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.exec()

    def save_user_settings(self, dialog):
        username = self.username_input.text()
        full_name = self.fullname_input.text()

        if not username or not full_name:
            QMessageBox.warning(self, "Ошибка", "Все поля должны быть заполнены!")
            return

        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        UPDATE user 
                        SET Username = %s, UserFullName = %s 
                        WHERE UserId = %s
                    """, (username, full_name, self.user_data['id']))
                    conn.commit()
                    # Обновляем локальные данные пользователя
                    self.user_data['username'] = username
                    self.user_data['full_name'] = full_name
                    self.setWindowTitle(
                        f"SmartУчеба - {self.user_data['full_name']} ({self.user_data['role'].capitalize()})")
                    QMessageBox.information(self, "Успех", "Данные пользователя успешно обновлены!")
                    dialog.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить изменения: {str(e)}")

    def save_db_settings(self):
        host = self.db_host_input.text().strip()
        port = self.db_port_input.text().strip()
        user = self.db_user_input.text().strip()
        password = self.db_pass_input.text()
        database = self.db_name_input.text().strip()

        if not all([host, port, user, database]):
            QMessageBox.warning(self, "Ошибка", "Все поля должны быть заполнены!")
            return

        try:
            port = int(port)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Порт должен быть числом!")
            return

        try:
            # Обновляем настройки
            DB_Settings.set_config({
                'host': host,
                'port': port,
                'user': user,
                'password': password,
                'database': database
            })

            # Пробуем новое подключение
            with DB_Settings.get_connection() as conn:
                conn.ping()
                QMessageBox.information(self, "Успех", "Настройки базы данных успешно обновлены!")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить настройки:\n{str(e)}")

    def generate_schedules(self):
        try:
            # Проверка наличия необходимых данных
            if not self.check_required_data():
                return

            with DB_Settings.get_connection() as conn:
                cursor = conn.cursor()

                current_year, current_semester = self.get_current_academic_period()

                # Исправленный запрос с правильными параметрами
                workloads = self.get_workloads_for_period(cursor, current_year, current_semester)

                classrooms = self.get_available_classrooms(cursor)
                existing_schedule = self.get_existing_schedule(cursor)

                generated_schedule = []
                for workload in workloads:
                    slot = self.find_available_slot(workload, classrooms, existing_schedule + generated_schedule)

                    if slot:
                        schedule_entry = (
                            workload['WorkloadId'],
                            slot['classroom_id'],
                            slot['day'],
                            slot['start_time'],
                            slot['end_time']
                        )
                        generated_schedule.append(schedule_entry)

                if generated_schedule:
                    # Исправленный вызов с правильным форматом параметров
                    self.save_schedule_to_db(cursor, generated_schedule)
                    conn.commit()
                    QMessageBox.information(self, "Успех", f"Добавлено {len(generated_schedule)} занятий")
                else:
                    QMessageBox.warning(self, "Ошибка", "Не удалось сгенерировать расписание")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка генерации: {str(e)}")
            if 'conn' in locals():
                conn.rollback()

    def check_required_data(self):
        """Проверяет наличие минимально необходимых данных"""
        with DB_Settings.get_connection() as conn:
            cursor = conn.cursor()
            # Проверяем есть ли группы, преподаватели, предметы и аудитории
            tables = ['StudentGroup', 'user', 'Subject', 'Classroom']
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                if cursor.fetchone()[0] == 0:
                    return False
            return True

    def get_current_academic_period(self):
        """Возвращает текущий учебный год и семестр"""
        # Можно реализовать более сложную логику определения периода
        return "2023-2024", 1

    def get_workloads_for_period(self, cursor, year, semester):
        """Получает нагрузки преподавателей для указанного периода"""
        query = """
        SELECT w.WorkloadId, w.TeacherId, w.SubjectId, w.GroupId, w.Hours, 
               s.SubjectName, g.GroupName, w.LessonType
        FROM TeacherWorkload w
        JOIN Subject s ON w.SubjectId = s.SubjectId
        JOIN StudentGroup g ON w.GroupId = g.GroupId
        WHERE w.AcademicYear = ? AND w.Semester = ?
        """
        cursor.execute(query, (year, semester))
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_available_classrooms(self, cursor):
        """Получает список доступных аудиторий"""
        cursor.execute("SELECT ClassroomId, RoomNumber, Capacity, RoomType FROM Classroom")
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_existing_schedule(self, cursor):
        """Получает уже существующее расписание"""
        cursor.execute("""
        SELECT s.ScheduleId, s.WorkloadId, s.ClassroomId, s.DayOfWeek, 
               s.StartTime, s.EndTime, w.GroupId, w.TeacherId
        FROM Schedule s
        JOIN TeacherWorkload w ON s.WorkloadId = w.WorkloadId
        """)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def find_available_slot(self, workload, classrooms, existing_schedule):
        """Находит доступный слот для занятия с учетом ограничений"""
        # Пример простой реализации - нужно доработать
        days_of_week = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
        time_slots = [
            ('09:00:00', '10:30:00'),
            ('11:00:00', '12:30:00'),
            ('13:00:00', '14:30:00'),
            ('15:00:00', '16:30:00')
        ]
        # Фильтруем аудитории по типу занятия и вместимости
        suitable_classrooms = [
            room for room in classrooms
            if self.is_classroom_suitable(room, workload)
        ]
        for day in days_of_week:
            for start_time, end_time in time_slots:
                for room in suitable_classrooms:
                    if not self.has_conflict(day, start_time, end_time, room['ClassroomId'],
                                             workload['TeacherId'], workload['GroupId'],
                                             existing_schedule):
                        return {
                            'day': day,
                            'start_time': start_time,
                            'end_time': end_time,
                            'classroom_id': room['ClassroomId']
                        }
        return None

    def check_required_data(self):
        """Проверяет наличие минимально необходимых данных для генерации расписания"""
        required_tables = {
            'StudentGroup': "Не найдено ни одной учебной группы",
            'user': "Нет данных о пользователях (преподавателях/студентах)",
            'Subject': "Не добавлено ни одного предмета",
            'Classroom': "Не добавлено ни одной аудитории",
            'TeacherWorkload': "Нет данных о нагрузке преподавателей"
        }
        try:
            with DB_Settings.get_connection() as conn:
                cursor = conn.cursor()
                # Проверяем наличие данных в каждой требуемой таблице
                missing_data = []
                for table, error_msg in required_tables.items():
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    if cursor.fetchone()[0] == 0:
                        missing_data.append(error_msg)
                if missing_data:
                    QMessageBox.warning(self, "Недостаточно данных",
                                        "Для генерации расписания необходимо:\n\n" +
                                        "\n".join(missing_data))
                    return False
                # Дополнительная проверка - есть ли хотя бы один преподаватель
                cursor.execute("SELECT COUNT(*) FROM user WHERE UserPositionId = 1")  # 1 - teacher
                if cursor.fetchone()[0] == 0:
                    QMessageBox.warning(self, "Недостаточно данных",
                                        "В системе нет ни одного преподавателя")
                    return False
                # Проверяем, есть ли назначенная нагрузка
                current_year, current_semester = self.get_current_academic_period()
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM TeacherWorkload 
                    WHERE AcademicYear = ? AND Semester = ?
                """, (current_year, current_semester))
                if cursor.fetchone()[0] == 0:
                    QMessageBox.warning(self, "Недостаточно данных",
                                        f"Нет учебной нагрузки на {current_semester} семестр {current_year} учебного года")
                    return False
                return True
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при проверке данных: {str(e)}")
            return False

    def is_classroom_suitable(self, classroom, workload):
        """Проверяет подходит ли аудитория для занятия"""
        # Проверяем тип аудитории и вместимость
        if workload['LessonType'] == 'Лекция' and classroom['RoomType'] != 'Лекционная':
            return False
        # Дополнительные проверки...
        return True

    def has_conflict(self, day, start_time, end_time, classroom_id, teacher_id, group_id, schedule):
        """Проверяет есть ли конфликт в расписании"""
        for entry in schedule:
            if (entry['DayOfWeek'] == day and
                    ((entry['StartTime'] <= start_time < entry['EndTime']) or
                     (entry['StartTime'] < end_time <= entry['EndTime']) or
                     (start_time <= entry['StartTime'] and end_time >= entry['EndTime']))):
                # Проверяем конфликты по аудитории, преподавателю и группе
                if (entry['ClassroomId'] == classroom_id or
                        entry.get('TeacherId') == teacher_id or
                        entry.get('GroupId') == group_id):
                    return True
        return False

    def save_schedule_to_db(self, cursor, schedule):
        """Сохраняет сгенерированное расписание в базу данных"""
        # Удаляем старое расписание
        cursor.execute("DELETE FROM Schedule")
        # Добавляем новые записи
        insert_query = """
        INSERT INTO Schedule (WorkloadId, ClassroomId, DayOfWeek, StartTime, EndTime)
        VALUES (?, ?, ?, ?, ?)
        """
        cursor.executemany(insert_query, schedule)

    def load_classrooms(self):
        """Загружает список аудиторий в комбобокс"""
        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT ClassroomId, RoomNumber FROM Classroom")
                    classrooms = cursor.fetchall()
                    for classroom_id, room_number in classrooms:
                        self.classroom_combo.addItem(room_number, classroom_id)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить аудитории: {str(e)}")

    def submit_request(self, dialog):
        """Отправляет заявку на изменение"""
        if not self.reason_edit.toPlainText():
            QMessageBox.warning(self, "Ошибка", "Укажите причину изменения")
            return

        try:
            with DB_Settings.get_connection() as conn:
                with conn.cursor() as cursor:
                    # В реальном приложении нужно определить ScheduleId для изменения
                    cursor.execute("""
                        INSERT INTO ScheduleChangeRequests 
                        (TeacherId, RequestDate, ChangeType, Reason, Status, NewDate, NewClassroomId)
                        VALUES (%s, NOW(), %s, %s, 'На рассмотрении', %s, %s)
                    """, (
                        self.user_data['id'],
                        self.type_combo.currentText(),
                        self.reason_edit.toPlainText(),
                        self.date_edit.date().toString("yyyy-MM-dd"),
                        self.classroom_combo.currentData()
                    ))

                    conn.commit()
                    QMessageBox.information(self, "Успех", "Заявка отправлена на рассмотрение")
                    print('ok')
                    dialog.accept()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось отправить заявку: {str(e)}")

    def show_request_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Запрос изменения")
        form = QFormLayout(dialog)

        date_edit = QDateEdit()
        reason_edit = QTextEdit()

        form.addRow("Дата изменения:", date_edit)
        form.addRow("Причина:", reason_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)  # Исправлено здесь
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        form.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:  # Исправлено здесь
            QMessageBox.information(self, "Успешно", "Запрос отправлен")


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    window = MainWindow(user_role="teacher")
    window.show()
    sys.exit(app.exec())
