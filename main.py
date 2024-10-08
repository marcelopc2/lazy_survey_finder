import streamlit as st
import requests
import pandas as pd
from io import BytesIO
import os
from decouple import config

canvas_url = "https://canvas.uautonoma.cl"
canvas_token = config('CANVAS_API_TOKEN')
if not canvas_token:
    raise ValueError(
        "El token de acceso no está configurado. Por favor, establece la variable de entorno 'CANVAS_API_TOKEN'.")
headers = {
    'Authorization': f'Bearer {canvas_token}'
}
st.set_page_config(page_title="Lazy Survey Data Finder 0.2", layout='wide')

# Inicializar el estado de la sesión
if 'selected_surveys' not in st.session_state:
    st.session_state['selected_surveys'] = {}
if 'previous_course_ids' not in st.session_state:
    st.session_state['previous_course_ids'] = ''
if 'show_results' not in st.session_state:
    st.session_state['show_results'] = False
if 'results_data' not in st.session_state:
    st.session_state['results_data'] = {}
if 'program_names' not in st.session_state:
    st.session_state['program_names'] = {}
if 'generated_reports' not in st.session_state:
    st.session_state['generated_reports'] = {}

# Funciones cacheadas
@st.cache_data
def get_course_info(course_id):
    course_url = f"{canvas_url}/api/v1/courses/{course_id}"
    course_response = requests.get(course_url, headers=headers)
    if course_response.status_code == 200:
        return course_response.json()
    else:
        return None

@st.cache_data
def get_account_info(account_id):
    account_url = f"{canvas_url}/api/v1/accounts/{account_id}"
    account_response = requests.get(account_url, headers=headers)
    if account_response.status_code == 200:
        return account_response.json()
    else:
        return None

@st.cache_data
def get_quizzes(course_id):
    quizzes_url = f"{canvas_url}/api/v1/courses/{course_id}/quizzes"
    quizzes_response = requests.get(quizzes_url, headers=headers)
    if quizzes_response.status_code == 200:
        return quizzes_response.json()
    else:
        return None

# Función para generar el reporte de una encuesta y convertirlo a Excel
def generate_report(course_id, quiz_id, quiz_title):
    report_url = f"{canvas_url}/api/v1/courses/{course_id}/quizzes/{quiz_id}/reports"
    report_payload = {
        "quiz_report": {
            "report_type": "student_analysis",
            "includes_all_versions": True
        }
    }

    # Generar el reporte
    report_response = requests.post(report_url, headers=headers, json=report_payload)
    if report_response.status_code == 200:
        report = report_response.json()
        report_id = report['id']

        # Esperar a que el reporte esté listo
        import time
        status_url = report['progress_url']
        while True:
            progress_response = requests.get(status_url, headers=headers)
            progress = progress_response.json()
            if progress['workflow_state'] == 'completed':
                break
            time.sleep(1)

        # Obtener el enlace de descarga del reporte
        report_status_url = f"{canvas_url}/api/v1/courses/{course_id}/quizzes/{quiz_id}/reports/{report_id}"
        report_status_response = requests.get(report_status_url, headers=headers)
        if report_status_response.status_code == 200:
            report_data = report_status_response.json()
            file_url = report_data['file']['url']

            # Descargar el archivo CSV
            file_response = requests.get(file_url, headers=headers)
            if file_response.status_code == 200:
                # Convertir el contenido CSV a Excel
                csv_content = file_response.content.decode('utf-8')
                df = pd.read_csv(BytesIO(file_response.content))

                # Crear un archivo Excel en memoria
                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    df.to_excel(writer, index=False, sheet_name='Reporte')
                    writer.close()
                excel_content = output.getvalue()

                file_name = f"Reporte_{quiz_title.replace(' ', '_')}.xlsx"
                return excel_content, file_name
            else:
                st.error("Error al descargar el archivo del reporte.")
                return None, None
        else:
            st.error("Error al obtener el estado del reporte.")
            return None, None
    else:
        st.error("Error al generar el reporte.")
        return None, None

# Título de la aplicación
st.title("Lazy Survey Data Finder 0.2")

# Ingresar IDs de cursos
course_ids_input = st.text_area("Ingresa los IDs de los cursos que quieras analizar:")

# Limpiar el caché y resetear variables si los IDs de cursos han cambiado
if course_ids_input != st.session_state.get('previous_course_ids', ''):
    st.cache_data.clear()
    st.session_state['selected_surveys'] = {}
    st.session_state['previous_course_ids'] = course_ids_input
    st.session_state['show_results'] = False
    st.session_state['results_data'] = {}
    st.session_state['program_names'] = {}
    st.session_state['generated_reports'] = {}
    for key in list(st.session_state.keys()):
        if key.startswith('survey_checkbox_'):
            del st.session_state[key]

if course_ids_input:
    # Procesar los IDs de cursos
    course_ids_input_list = [cid.strip() for cid in course_ids_input.replace(',', ' ').split() if cid.strip()]
    course_ids = []
    seen = set()
    for cid in course_ids_input_list:
        if cid not in seen:
            course_ids.append(cid)
            seen.add(cid)

    if not st.session_state['show_results']:
        selection_container = st.container()

        with selection_container:
            selected_surveys = {}
            for course_id in course_ids:
                # Obtener información del curso
                course_info = get_course_info(course_id)
                if course_info:
                    course_name = course_info.get('name', f"Curso ID: {course_id}")
                    account_id = course_info.get('account_id')
                    account_info = get_account_info(account_id)
                    if account_info:
                        program_name = account_info.get('name', 'No especificado')
                    else:
                        program_name = 'No especificado'
                else:
                    course_name = f"Curso ID: {course_id}"
                    program_name = 'No especificado'

                st.session_state['program_names'][course_id] = program_name

                st.subheader(f"{course_name} (ID: {course_id})")
                # Obtener quizzes del curso
                quizzes = get_quizzes(course_id)
                if quizzes:
                    # Filtrar quizzes que son encuestas
                    surveys = [quiz for quiz in quizzes if quiz['quiz_type'] in ['survey', 'graded_survey']]
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
                                'course_name': course_name,
                                'surveys': selected
                            }
                    else:
                        st.write("No se encontraron encuestas en este curso.")
                else:
                    st.error(f"Error al obtener las encuestas del curso {course_id}.")

            # Botón para procesar las encuestas seleccionadas
            if selected_surveys:
                if st.button("Buscar informacion de las encuestas seleccionadas"):
                    st.session_state['selected_surveys'] = selected_surveys
                    st.session_state['show_results'] = True
                    selection_container.empty()
                    for key in list(st.session_state.keys()):
                        if key.startswith('survey_checkbox_'):
                            del st.session_state[key]
                    st.rerun()
            else:
                st.write("No has seleccionado ninguna encuesta.")

# Mostrar resultados si se han seleccionado encuestas y se presionó el botón
if st.session_state['show_results']:
    selected_surveys = st.session_state['selected_surveys']
    all_results = []

    for course_id in course_ids:
        if course_id in selected_surveys:
            data = selected_surveys[course_id]
            course_name = data['course_name']
            program_name = st.session_state['program_names'].get(course_id, 'No especificado')
            course_link = f"{canvas_url}/courses/{course_id}"
            surveys = data['surveys']

            # Obtener número total de alumnos inscritos
            enrollments_url = f"{canvas_url}/api/v1/courses/{course_id}/enrollments"
            enrollments_params = {
                'type': ['StudentEnrollment'],
                'state': ['active'],
                'per_page': 100
            }
            enrollments = []
            enrollments_url_page = enrollments_url
            while enrollments_url_page:
                enrollments_response = requests.get(enrollments_url_page, headers=headers, params=enrollments_params)
                if enrollments_response.status_code == 200:
                    enrollments_page = enrollments_response.json()
                    enrollments.extend([e for e in enrollments_page if e['user']['name'] != 'Test Student'])
                    if 'next' in enrollments_response.links:
                        enrollments_url_page = enrollments_response.links['next']['url']
                        enrollments_params = None
                    else:
                        enrollments_url_page = None
                else:
                    st.error(f"Error al obtener las inscripciones del curso {course_name}: {enrollments_response.status_code}")
                    break

            num_students = len(enrollments)
            if num_students == 0:
                st.write(f"{course_name} (ID: {course_id})")
                st.write("No se encontraron alumnos inscritos en este curso.")
                continue

            # Obtener IDs de estudiantes reales
            student_ids = [e['user_id'] for e in enrollments]

            # Crear una lista para almacenar los resultados de las encuestas
            survey_results = []

            for survey in surveys:
                # Obtener envíos de la encuesta
                submissions = []
                submissions_url = f"{canvas_url}/api/v1/courses/{course_id}/quizzes/{survey['id']}/submissions"
                submissions_params = {
                    'per_page': 100,
                    'include': ['submission']
                }
                submissions_url_page = submissions_url
                while submissions_url_page:
                    submissions_response = requests.get(submissions_url_page, headers=headers, params=submissions_params)
                    if submissions_response.status_code == 200:
                        submissions_page = submissions_response.json()['quiz_submissions']
                        submissions.extend(submissions_page)
                        if 'next' in submissions_response.links:
                            submissions_url_page = submissions_response.links['next']['url']
                            submissions_params = None
                        else:
                            submissions_url_page = None
                    else:
                        st.error(f"Error al obtener las respuestas de la encuesta '{survey['title']}' en el curso '{course_name}': {submissions_response.status_code}")
                        break

                # Filtrar envíos de estudiantes reales
                submissions = [s for s in submissions if s['user_id'] in student_ids]
                num_submissions = len(submissions)
                num_not_submitted = num_students - num_submissions
                percentage_submitted = (num_submissions / num_students) * 100 if num_students > 0 else 0
                percentage_not_submitted = 100 - percentage_submitted

                # Agregar resultados a la lista
                survey_results.append({
                    'Programa': program_name,
                    'Curso': course_name,
                    'Link': course_link,
                    'Encuesta': survey['title'],
                    'N° Inscritos': num_students,
                    'N° Contestadas': num_submissions if num_submissions > 0 else '---',
                    '% Contestadas': f"{percentage_submitted:.0f}%" if num_submissions > 0 else '---',
                    'No Contestadas': num_not_submitted if num_submissions > 0 else '---',
                    '% No Contestadas': f"{percentage_not_submitted:.0f}%" if num_submissions > 0 else '---'
                })

            # Crear DataFrame y mostrar tabla sin índice
            df = pd.DataFrame(survey_results)
            df_display = df[['Encuesta', 'N° Inscritos', 'N° Contestadas', '% Contestadas', 'No Contestadas', '% No Contestadas']]
            df_display.reset_index(drop=True, inplace=True)
            st.write(f"##### {course_name}")
            st.dataframe(df_display, hide_index=True)

            # Agregar resultados al total
            all_results.append({
                'df': df,
                'course_name': course_name,
                'program_name': program_name,
                'course_link': course_link,
                'course_id': course_id
            })

            # Mostrar botones de generación y descarga de reportes
            for survey in surveys:
                survey_key = f"{course_id}_{survey['id']}"
                # st.write(f"### Encuesta: {survey['title']} (ID: {survey['id']})")

                if survey_key in st.session_state['generated_reports']:
                    # El reporte ya fue generado, mostrar botón de descarga
                    report_content = st.session_state['generated_reports'][survey_key]['content']
                    file_name = st.session_state['generated_reports'][survey_key]['file_name']
                    st.download_button(
                        label=f"Descargar Reporte: {survey['title']}", #Reporte de '{survey['title']}'",
                        data=report_content,
                        file_name=file_name,
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        key=f"download_{survey_key}"
                    )
                else:
                    # El reporte no ha sido generado, mostrar botón de generación
                    if st.button(f"Generar reporte: {survey['title']}", key=f"generate_{survey_key}"): #Reporte de '{survey['title']}'", key=f"generate_{survey_key}"):
                        with st.spinner('Generando'):
                            report_content, file_name = generate_report(course_id, survey['id'], survey['title'])
                            if report_content:
                                st.session_state['generated_reports'][survey_key] = {
                                    'content': report_content,
                                    'file_name': file_name
                                }
                                st.rerun()

    # Generar el archivo Excel personalizado en una sola hoja
    if all_results:
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            workbook = writer.book

            # Estilos personalizados
            header_format = workbook.add_format({'bold': True, 'font_size': 12})
            bold_format = workbook.add_format({'bold': True})
            percentage_format = workbook.add_format({'num_format': '0%'})
            center_format = workbook.add_format({'align': 'center'})
            link_format = workbook.add_format({'font_color': 'blue', 'underline': 1})

            worksheet = workbook.add_worksheet('Resultados')
            writer.sheets['Resultados'] = worksheet

            current_row = 0

            for result in all_results:
                df = result['df']
                course_name = result['course_name']
                program_name = result['program_name']
                course_link = result['course_link']

                df_to_write = df[['Encuesta', 'N° Inscritos', 'N° Contestadas', '% Contestadas', 'No Contestadas', '% No Contestadas']]
                df_to_write.replace('---', '', inplace=True)

                # Escribir información adicional
                worksheet.write(current_row, 0, 'Programa:', bold_format)
                worksheet.write(current_row, 1, program_name)
                current_row += 1
                worksheet.write(current_row, 0, 'Curso:', bold_format)
                worksheet.write(current_row, 1, course_name)
                current_row += 1
                worksheet.write(current_row, 0, 'Link:', bold_format)
                worksheet.write_url(current_row, 1, course_link, string=course_link, cell_format=link_format)
                current_row += 2

                # Escribir encabezados de la tabla
                for col_num, value in enumerate(df_to_write.columns.values):
                    worksheet.write(current_row, col_num, value, header_format)
                current_row += 1

                # Escribir datos de la tabla
                for row in df_to_write.itertuples(index=False):
                    for col_num, cell_value in enumerate(row):
                        worksheet.write(current_row, col_num, cell_value)
                    current_row += 1

                # Espacio entre tablas
                current_row += 2

            # Ajustar ancho de columnas
            worksheet.set_column('A:A', 30)
            worksheet.set_column('B:B', 12, center_format)
            worksheet.set_column('C:C', 15, center_format)
            worksheet.set_column('D:D', 15, center_format)
            worksheet.set_column('E:E', 15, center_format)
            worksheet.set_column('F:F', 17, center_format)

        processed_data = output.getvalue()
        
        st.markdown("---")
        
        st.download_button(
            label="Descargar TODOS los resultados en Excel",
            data=processed_data,
            file_name='resultados_encuestas.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    st.markdown("---")
