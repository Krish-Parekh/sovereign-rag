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
