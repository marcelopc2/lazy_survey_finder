import streamlit as st
import requests
import pandas as pd
from io import BytesIO
from decouple import config
from datetime import datetime
import time

canvas_url = "https://canvas.uautonoma.cl"
canvas_token = config("CANVAS_API_TOKEN")

if not canvas_token:
    raise ValueError(
        "El token de acceso no está configurado. Por favor, establece la variable de entorno 'CANVAS_API_TOKEN'."
    )

headers = {"Authorization": f"Bearer {canvas_token}"}

st.set_page_config(page_title="Lazy Survey Data Finder WEB 1.0", layout="wide")

if "selected_surveys" not in st.session_state:
    st.session_state["selected_surveys"] = {}
if "previous_course_ids" not in st.session_state:
    st.session_state["previous_course_ids"] = ""
if "show_results" not in st.session_state:
    st.session_state["show_results"] = False
if "results_data" not in st.session_state:
    st.session_state["results_data"] = {}
if "program_names" not in st.session_state:
    st.session_state["program_names"] = {}
if "generated_reports" not in st.session_state:
    st.session_state["generated_reports"] = {}

def _fmt_dt(iso_str: str) -> str:
    """ISO Canvas -> YYYY-MM-DD. Si None/vacío -> '-'."""
    if not iso_str:
        return "-"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except Exception:
        return str(iso_str)

@st.cache_data
def get_course_start_date(course_id: str):
    """start_at del curso (si existe)."""
    course_url = f"{canvas_url}/api/v1/courses/{course_id}"
    r = requests.get(course_url, headers=headers)
    if r.status_code == 200:
        data = r.json()
        return data.get("start_at") or None
    return None

@st.cache_data
def get_last_assignment_due_at(course_id: str):
    """
    Busca la fecha máxima due_at en Assignments del curso.
    Si no hay due_at -> None
    """
    next_url = f"{canvas_url}/api/v1/courses/{course_id}/assignments?per_page=100"
    due_dates = []

    while next_url:
        r = requests.get(next_url, headers=headers)
        if r.status_code != 200:
            break

        page = r.json()
        if isinstance(page, list):
            for a in page:
                if isinstance(a, dict) and a.get("due_at"):
                    due_dates.append(a["due_at"])

        next_url = r.links.get("next", {}).get("url")

    if not due_dates:
        return None

    def to_dt(x):
        return datetime.fromisoformat(x.replace("Z", "+00:00"))

    return max(due_dates, key=lambda x: to_dt(x))

def render_course_title_with_dates(course_name: str, course_id: str):
    """Título del curso + fechas al lado, verde si existe fecha."""
    start_txt = _fmt_dt(get_course_start_date(course_id))
    close_txt = _fmt_dt(get_last_assignment_due_at(course_id))

    start_color = "green" if start_txt != "-" else "#999999"
    close_color = "green" if close_txt != "-" else "#999999"

    st.markdown(
        f"""
        <h3 style="margin-bottom:0;">
            {course_name} (ID: {course_id})
            <span style="font-size:0.8em; font-weight:normal;">
                (
                <span style="color:{start_color};">Inicio: {start_txt}</span>
                |
                <span style="color:{close_color};">Cierre: {close_txt}</span>
                )
            </span>
        </h3>
        """,
        unsafe_allow_html=True
    )

@st.cache_data
def get_course_info(course_id):
    course_url = f"{canvas_url}/api/v1/courses/{course_id}"
    course_response = requests.get(course_url, headers=headers)
    if course_response.status_code == 200:
        return course_response.json()
    return None

@st.cache_data
def get_account_info(account_id):
    account_url = f"{canvas_url}/api/v1/accounts/{account_id}"
    account_response = requests.get(account_url, headers=headers)
    if account_response.status_code == 200:
        return account_response.json()
    return None

@st.cache_data
def get_quizzes(course_id):
    quizzes_url = f"{canvas_url}/api/v1/courses/{course_id}/quizzes"
    quizzes_response = requests.get(quizzes_url, headers=headers)
    if quizzes_response.status_code == 200:
        return quizzes_response.json()
    return None

@st.cache_data
def generate_report(course_id, quiz_id, quiz_title):
    report_url = f"{canvas_url}/api/v1/courses/{course_id}/quizzes/{quiz_id}/reports"
    report_payload = {
        "quiz_report": {"report_type": "student_analysis", "includes_all_versions": True}
    }

    report_response = requests.post(report_url, headers=headers, json=report_payload)
    if report_response.status_code == 200:
        report = report_response.json()
        report_id = report["id"]

        status_url = report["progress_url"]
        while True:
            progress_response = requests.get(status_url, headers=headers)
            progress = progress_response.json()
            if progress.get("workflow_state") == "completed":
                break
            time.sleep(1)

        report_status_url = f"{canvas_url}/api/v1/courses/{course_id}/quizzes/{quiz_id}/reports/{report_id}"
        report_status_response = requests.get(report_status_url, headers=headers)
        if report_status_response.status_code == 200:
            report_data = report_status_response.json()
            file_url = report_data["file"]["url"]

            file_response = requests.get(file_url, headers=headers)
            if file_response.status_code == 200:
                df = pd.read_csv(BytesIO(file_response.content))

                output = BytesIO()
                with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                    df.to_excel(writer, index=False, sheet_name="Reporte")

                excel_content = output.getvalue()
                file_name = f"Reporte_{quiz_title.replace(' ', '_')}.xlsx"
                return excel_content, file_name

            st.error("Error al descargar el archivo del reporte.")
            return None, None

        st.error("Error al obtener el estado del reporte.")
        return None, None

    st.error("Error al generar el reporte.")
    return None, None

st.title("Lazy Survey Data Finder WEB 1.0")

course_ids_input = st.text_area("Ingresa los IDs de los cursos que quieras analizar:")

if course_ids_input != st.session_state.get("previous_course_ids", ""):
    st.cache_data.clear()
    st.session_state["selected_surveys"] = {}
    st.session_state["previous_course_ids"] = course_ids_input
    st.session_state["show_results"] = False
    st.session_state["results_data"] = {}
    st.session_state["program_names"] = {}
    st.session_state["generated_reports"] = {}
    for key in list(st.session_state.keys()):
        if key.startswith("survey_checkbox_"):
            del st.session_state[key]

course_ids = []
if course_ids_input:
    course_ids_input_list = [
        cid.strip() for cid in course_ids_input.replace(",", " ").split() if cid.strip()
    ]
    seen = set()
    for cid in course_ids_input_list:
        if cid not in seen:
            course_ids.append(cid)
            seen.add(cid)


if course_ids and not st.session_state["show_results"]:
    selection_container = st.container()

    with selection_container:
        selected_surveys = {}

        for course_id in course_ids:
            course_info = get_course_info(course_id)

            if course_info:
                course_name = course_info.get("name", f"Curso ID: {course_id}")
                account_id = course_info.get("account_id")
                account_info = get_account_info(account_id) if account_id else None
                program_name = account_info.get("name", "No especificado") if account_info else "No especificado"
            else:
                course_name = f"Curso ID: {course_id}"
                program_name = "No especificado"

            st.session_state["program_names"][course_id] = program_name

            render_course_title_with_dates(course_name, course_id)

            quizzes = get_quizzes(course_id)
            if quizzes:
                surveys = [quiz for quiz in quizzes if quiz.get("quiz_type") in ["survey", "graded_survey"]]
                if surveys:
                    st.write("Selecciona las encuestas que deseas analizar:")
                    selected = []
                    for idx, survey in enumerate(surveys):
                        checkbox_label = f"{survey['title']} (ID: {survey['id']})"
                        key = f"survey_checkbox_{course_id}_{survey['id']}_{idx}"
                        is_selected = st.checkbox(checkbox_label, key=key)
                        if is_selected:
                            selected.append(survey)

                    if selected:
                        selected_surveys[course_id] = {
                            "course_name": course_name,
                            "surveys": selected
                        }
                else:
                    st.write("No se encontraron encuestas en este curso.")
            else:
                st.error(f"Error al obtener las encuestas del curso {course_id}.")

        if selected_surveys:
            if st.button("Buscar informacion de las encuestas seleccionadas"):
                st.session_state["selected_surveys"] = selected_surveys
                st.session_state["show_results"] = True
                selection_container.empty()
                for key in list(st.session_state.keys()):
                    if key.startswith("survey_checkbox_"):
                        del st.session_state[key]
                st.rerun()
        else:
            st.write("No has seleccionado ninguna encuesta.")


if st.session_state["show_results"] and course_ids:
    selected_surveys = st.session_state["selected_surveys"]
    all_results = []

    for course_id in course_ids:
        if course_id not in selected_surveys:
            continue

        data = selected_surveys[course_id]
        course_name = data["course_name"]
        program_name = st.session_state["program_names"].get(course_id, "No especificado")
        course_link = f"{canvas_url}/courses/{course_id}"
        surveys = data["surveys"]

        render_course_title_with_dates(course_name, course_id)

        enrollments_url = f"{canvas_url}/api/v1/courses/{course_id}/enrollments"
        enrollments_params = {
            "type": ["StudentEnrollment"],
            "state": ["active"],
            "per_page": 100
        }

        enrollments = []
        enrollments_url_page = enrollments_url
        while enrollments_url_page:
            enrollments_response = requests.get(enrollments_url_page, headers=headers, params=enrollments_params)
            if enrollments_response.status_code == 200:
                enrollments_page = enrollments_response.json()
                enrollments.extend([e for e in enrollments_page if e["user"]["name"] != "Test Student"])
                if "next" in enrollments_response.links:
                    enrollments_url_page = enrollments_response.links["next"]["url"]
                    enrollments_params = None
                else:
                    enrollments_url_page = None
            else:
                st.error(
                    f"Error al obtener las inscripciones del curso {course_name}: {enrollments_response.status_code}"
                )
                break

        num_students = len(enrollments)
        if num_students == 0:
            st.write("No se encontraron alumnos inscritos en este curso.")
            st.markdown("---")
            continue

        student_ids = [e["user_id"] for e in enrollments]
        survey_results = []

        for survey in surveys:
            submissions = []
            submissions_url = f"{canvas_url}/api/v1/courses/{course_id}/quizzes/{survey['id']}/submissions"
            submissions_params = {"per_page": 100, "include": ["submission"]}

            submissions_url_page = submissions_url
            while submissions_url_page:
                submissions_response = requests.get(submissions_url_page, headers=headers, params=submissions_params)
                if submissions_response.status_code == 200:
                    submissions_page = submissions_response.json()["quiz_submissions"]
                    submissions.extend(submissions_page)
                    if "next" in submissions_response.links:
                        submissions_url_page = submissions_response.links["next"]["url"]
                        submissions_params = None
                    else:
                        submissions_url_page = None
                else:
                    st.error(
                        f"Error al obtener las respuestas de la encuesta '{survey['title']}' en el curso '{course_name}': "
                        f"{submissions_response.status_code}"
                    )
                    break

            submissions = [s for s in submissions if s["user_id"] in student_ids]
            num_submissions = len(submissions)
            num_not_submitted = num_students - num_submissions
            percentage_submitted = (num_submissions / num_students) * 100 if num_students > 0 else 0
            percentage_not_submitted = 100 - percentage_submitted

            survey_results.append({
                "Programa": program_name,
                "Curso": course_name,
                "Link": course_link,
                "Encuesta": survey["title"],
                "N° Inscritos": num_students,
                "N° Contestadas": num_submissions if num_submissions > 0 else "---",
                "% Contestadas": f"{percentage_submitted:.0f}%" if num_submissions > 0 else "---",
                "No Contestadas": num_not_submitted if num_submissions > 0 else "---",
                "% No Contestadas": f"{percentage_not_submitted:.0f}%" if num_submissions > 0 else "---"
            })

        df = pd.DataFrame(survey_results)
        df_display = df[["Encuesta", "N° Inscritos", "N° Contestadas", "% Contestadas", "No Contestadas", "% No Contestadas"]]
        df_display.reset_index(drop=True, inplace=True)

        st.dataframe(df_display, hide_index=True)

        all_results.append({
            "df": df,
            "course_name": course_name,
            "program_name": program_name,
            "course_link": course_link,
            "course_id": course_id
        })

        for survey in surveys:
            survey_key = f"{course_id}_{survey['id']}"

            if survey_key in st.session_state["generated_reports"]:
                report_content = st.session_state["generated_reports"][survey_key]["content"]
                file_name = st.session_state["generated_reports"][survey_key]["file_name"]
                st.download_button(
                    label=f"Descargar Reporte: {survey['title']}",
                    data=report_content,
                    file_name=file_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"download_{survey_key}"
                )
            else:
                if st.button(f"Generar reporte: {survey['title']}", key=f"generate_{survey_key}"):
                    with st.spinner("Generando"):
                        report_content, file_name = generate_report(course_id, survey["id"], survey["title"])
                        if report_content:
                            st.session_state["generated_reports"][survey_key] = {
                                "content": report_content,
                                "file_name": file_name
                            }
                            st.rerun()

        st.markdown("---")

    if all_results:
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            workbook = writer.book

            header_format = workbook.add_format({"bold": True, "font_size": 12})
            bold_format = workbook.add_format({"bold": True})
            center_format = workbook.add_format({"align": "center"})
            link_format = workbook.add_format({"font_color": "blue", "underline": 1})

            worksheet = workbook.add_worksheet("Resultados")
            writer.sheets["Resultados"] = worksheet

            current_row = 0

            for result in all_results:
                df = result["df"]
                course_name = result["course_name"]
                program_name = result["program_name"]
                course_link = result["course_link"]

                df_to_write = df[["Encuesta", "N° Inscritos", "N° Contestadas", "% Contestadas", "No Contestadas", "% No Contestadas"]].copy()
                df_to_write.replace("---", "", inplace=True)

                worksheet.write(current_row, 0, "Programa:", bold_format)
                worksheet.write(current_row, 1, program_name)
                current_row += 1

                worksheet.write(current_row, 0, "Curso:", bold_format)
                worksheet.write(current_row, 1, course_name)
                current_row += 1

                worksheet.write(current_row, 0, "Link:", bold_format)
                worksheet.write_url(current_row, 1, course_link, string=course_link, cell_format=link_format)
                current_row += 2

                for col_num, value in enumerate(df_to_write.columns.values):
                    worksheet.write(current_row, col_num, value, header_format)
                current_row += 1

                for row in df_to_write.itertuples(index=False):
                    for col_num, cell_value in enumerate(row):
                        worksheet.write(current_row, col_num, cell_value)
                    current_row += 1

                current_row += 2

            worksheet.set_column("A:A", 30)
            worksheet.set_column("B:B", 12, center_format)
            worksheet.set_column("C:C", 15, center_format)
            worksheet.set_column("D:D", 15, center_format)
            worksheet.set_column("E:E", 15, center_format)
            worksheet.set_column("F:F", 17, center_format)

        processed_data = output.getvalue()

        st.download_button(
            label="Descargar TODOS los resultados en Excel",
            data=processed_data,
            file_name="resultados_encuestas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
