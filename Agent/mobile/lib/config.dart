/// API configuration
class ApiConfig {
  // Change this to your backend URL
  // For Android emulator: 10.0.2.2
  // For iOS simulator: localhost
  // For real device: your machine's local IP
  static const String baseUrl = 'http://localhost:8000';

  static const String chatEndpoint = '$baseUrl/api/chat';
  static const String conversationsEndpoint = '$baseUrl/api/conversations';
  static const String uploadVideoEndpoint = '$baseUrl/api/upload/video';
  static const String uploadVideosEndpoint = '$baseUrl/api/upload/videos';
  static const String videosEndpoint = '$baseUrl/api/videos';
}
