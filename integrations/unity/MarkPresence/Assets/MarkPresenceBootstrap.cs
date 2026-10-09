using System;
using System.Collections;
using UnityEngine;
using UnityEngine.Networking;

#if UNITY_EDITOR
using UnityEditor;
#endif

namespace MarkScout.Presence
{
    [Serializable]
    internal sealed class PresenceEnvelope
    {
        public PresenceState presence = new();
    }

    [Serializable]
    internal sealed class PresenceState
    {
        public string state = "offline";
        public string transcript = "";
        public string response = "";
        public string error = "";
    }

    internal sealed class MarkPresenceBootstrap : MonoBehaviour
    {
        private string endpoint = "";
        private string token = "";
        private PresenceState presence = new();
        private GameObject core = null!;
        private LineRenderer[] rings = Array.Empty<LineRenderer>();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Boot()
        {
            if (FindAnyObjectByType<MarkPresenceBootstrap>() != null)
            {
                return;
            }
            new GameObject("Mark Scout Presence").AddComponent<MarkPresenceBootstrap>();
        }

        private void Awake()
        {
            endpoint = (Environment.GetEnvironmentVariable("MARK_CONTROL_CENTER_URL") ?? "").TrimEnd('/');
            token = Environment.GetEnvironmentVariable("MARK_CONTROL_CENTER_TOKEN") ?? "";
            BuildScene();
            StartCoroutine(Poll());
        }

        private void Update()
        {
            var intensity = presence.state switch
            {
                "speaking" => 1.0f,
                "processing" => 0.85f,
                "recording" => 0.78f,
                "transcribing" => 0.58f,
                _ => 0.20f,
            };
            core.transform.Rotate(12f * Time.deltaTime, 28f * Time.deltaTime, 5f * Time.deltaTime);
            var pulse = 1f + Mathf.Sin(Time.time * (2f + intensity * 3f)) * (0.025f + intensity * 0.06f);
            core.transform.localScale = Vector3.one * pulse;
            for (var index = 0; index < rings.Length; index++)
            {
                rings[index].transform.Rotate(0f, 0f, (9f + index * 6f) * Time.deltaTime * (index % 2 == 0 ? 1f : -1f));
            }
        }

        private IEnumerator Poll()
        {
            while (true)
            {
                if (!string.IsNullOrWhiteSpace(endpoint) && !string.IsNullOrWhiteSpace(token))
                {
                    using var request = UnityWebRequest.Get(endpoint + "/api/voice/presence");
                    request.SetRequestHeader("Authorization", "Bearer " + token);
                    request.timeout = 2;
                    yield return request.SendWebRequest();
                    if (request.result == UnityWebRequest.Result.Success)
                    {
                        var parsed = JsonUtility.FromJson<PresenceEnvelope>(request.downloadHandler.text);
                        if (parsed?.presence != null)
                        {
                            presence = parsed.presence;
                            ApplyColor(StateColor(presence.state));
                        }
                    }
                }
                yield return new WaitForSecondsRealtime(0.4f);
            }
        }

        private void BuildScene()
        {
            if (Camera.main == null)
            {
                var cameraObject = new GameObject("Camera");
                cameraObject.tag = "MainCamera";
                var camera = cameraObject.AddComponent<Camera>();
                camera.transform.position = new Vector3(0f, 0f, -6.5f);
                camera.transform.LookAt(Vector3.zero);
                camera.clearFlags = CameraClearFlags.SolidColor;
                camera.backgroundColor = new Color(0.004f, 0.008f, 0.015f);
            }
            var lightObject = new GameObject("Key Light");
            var light = lightObject.AddComponent<Light>();
            light.type = LightType.Point;
            light.intensity = 2.2f;
            light.range = 12f;
            light.transform.position = new Vector3(0f, 1.5f, -3f);

            core = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            core.name = "Mark Core";
            rings = new LineRenderer[3];
            for (var ringIndex = 0; ringIndex < rings.Length; ringIndex++)
            {
                var ringObject = new GameObject("Presence Ring " + ringIndex);
                var line = ringObject.AddComponent<LineRenderer>();
                line.useWorldSpace = false;
                line.loop = true;
                line.widthMultiplier = 0.018f + ringIndex * 0.006f;
                line.positionCount = 128;
                var radius = 1.35f + ringIndex * 0.35f;
                for (var point = 0; point < line.positionCount; point++)
                {
                    var angle = point * Mathf.PI * 2f / line.positionCount;
                    line.SetPosition(point, new Vector3(Mathf.Cos(angle) * radius, Mathf.Sin(angle) * radius, 0f));
                }
                ringObject.transform.rotation = Quaternion.Euler(55f + ringIndex * 16f, 18f * ringIndex, 0f);
                rings[ringIndex] = line;
            }
            ApplyColor(StateColor("offline"));
        }

        private void ApplyColor(Color color)
        {
            var material = core.GetComponent<Renderer>().material;
            material.color = color * 0.35f;
            material.EnableKeyword("_EMISSION");
            material.SetColor("_EmissionColor", color * 1.6f);
            foreach (var ring in rings)
            {
                ring.startColor = color;
                ring.endColor = color;
            }
        }

        private static Color StateColor(string state) => state switch
        {
            "idle" => new Color(0.20f, 0.82f, 0.95f),
            "recording" => new Color(0.20f, 1.00f, 0.68f),
            "transcribing" => new Color(0.70f, 0.50f, 1.00f),
            "processing" => new Color(1.00f, 0.68f, 0.20f),
            "speaking" => new Color(0.25f, 0.92f, 1.00f),
            "error" => new Color(1.00f, 0.22f, 0.25f),
            _ => new Color(0.30f, 0.35f, 0.42f),
        };
    }

#if UNITY_EDITOR
    [InitializeOnLoad]
    internal static class MarkPresencePlayMode
    {
        static MarkPresencePlayMode()
        {
            if (!string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("MARK_CONTROL_CENTER_URL")))
            {
                EditorApplication.delayCall += () => EditorApplication.isPlaying = true;
            }
        }
    }
#endif
}
