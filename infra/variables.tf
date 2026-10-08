variable "region" {
  type    = string
  default = "ap-southeast-2"

  validation {
    condition     = var.region == "ap-southeast-2"
    error_message = "Every resource lives in ap-southeast-2."
  }
}

variable "chat_model" {
  type    = string
  default = "qwen.qwen3-32b-v1:0"
}


variable "api_rate_limit" {
  type        = number
  default     = 200
  description = "Steady requests per second for the API key. 200 matches the default Lambda concurrency of 1,000 at about 5 s per answer."
}

variable "api_burst_limit" {
  type        = number
  default     = 400
  description = "Requests the API key may send at once before API Gateway returns 429."
}

variable "api_daily_quota" {
  type        = number
  default     = 0
  description = "Requests per day for the API key. 0 means no daily quota."
}
