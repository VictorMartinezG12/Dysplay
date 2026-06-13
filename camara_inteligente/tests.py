import requests
import base64
from django.test import TestCase
from django.conf import settings


class GoogleVisionTest(TestCase):

    def test_conexion_api(self):
        """Esta descripción ayuda a Django a identificar el test"""
        print("\n=== 🚀 INICIANDO PRUEBA DE GOOGLE CLOUD VISION ===")

        # 1. Obtener la llave desde settings
        api_key = getattr(settings, "GOOGLE_VISION_KEY", None)
        if not api_key:
            print("❌ ERROR: No se encontró GOOGLE_VISION_KEY en settings.py")
            return

        print("Llave cargada correctamente.")

        # 2. Descargar una imagen pública de prueba
        url_imagen = "https://images.unsplash.com/photo-1510832198440-a52376950479?w=500"
        print("📥 Descargando imagen de prueba desde internet...")
        response_img = requests.get(url_imagen)

        if response_img.status_code != 200:
            print("❌ ERROR: No se pudo descargar la imagen de prueba de internet.")
            return

        image_base64 = base64.b64encode(response_img.content).decode('utf-8')

        # 3. Preparar la petición HTTP formal para la API de Google Cloud Vision
        url_api = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
        payload = {
            "requests": [
                {
                    "image": {"content": image_base64},
                    "features": [{"type": "LABEL_DETECTION", "maxResults": 5}]
                }
            ]
        }

        # 4. Enviar la solicitud a Google
        print("🧠 Enviando imagen a la Inteligencia Artificial de Google...")
        response_api = requests.post(url_api, json=payload)

        if response_api.status_code == 200:
            resultado = response_api.json()
            print("✅ ¡CONEXIÓN EXITOSA CON GOOGLE CLOUD VISION!")
            print("\n🔍 Objetos identificados en la imagen por la IA:")

            etiquetas = resultado['responses'][0].get('labelAnnotations', [])
            for etiqueta in etiquetas:
                print(f"   • {etiqueta['description']} (Confianza: {int(etiqueta['score'] * 100)}%)")

            print("\n=== 🎉 PRUEBA FINALIZADA CON ÉXITO ===")
        else:
            print(f"❌ ERROR DE API ({response_api.status_code}): {response_api.text}")