import json
import boto3
import base64
import hashlib
from datetime import datetime

s3 = boto3.client('s3')
polly = boto3.client('polly')
sns = boto3.client('sns')

# S3 Bucket for caching
CACHE_BUCKET = 'tts-cache-sedky-net'
CACHE_TTL_DAYS = 1  # Reserved for lifecycle logic if needed

# SNS Topic ARN (redacted)
SNS_TOPIC_ARN = 'arn:aws:sns:us-east-1:XXXXXXXXXXXX:TTSVoiceGenerated'

# Supported voice controls
ALLOWED_VOICES = {'Joanna', 'Matthew', 'Lucia', 'Zeina'}
NEURAL_VOICES = {'Joanna', 'Matthew', 'Lucia'}

def lambda_handler(event, context):
    try:
        # Parse input
        body = json.loads(event.get('body', '{}'))
        text = body.get('text', '')
        voice_id = body.get('voiceId', 'Joanna')

        # Validate voice
        if voice_id not in ALLOWED_VOICES:
            voice_id = 'Joanna'

        # Enforce 500-character limit
        if not text or len(text) > 500:
            return _error(400, "Input must be 1 to 500 characters.")

        # Determine Polly engine
        engine_type = 'neural' if voice_id in NEURAL_VOICES else 'standard'

        # Generate S3 key hash
        hash_key = hashlib.sha256(f"{voice_id}-{text}".encode()).hexdigest()
        s3_key = f"{voice_id}/{hash_key}.mp3"

        # Check if cached audio exists
        try:
            s3.head_object(Bucket=CACHE_BUCKET, Key=s3_key)
            presigned_url = s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': CACHE_BUCKET, 'Key': s3_key},
                ExpiresIn=3600
            )
            return _success(presigned_url)
        except s3.exceptions.ClientError as e:
            if e.response['Error']['Code'] != '404':
                raise

        # Call Polly to synthesize speech
        response = polly.synthesize_speech(
            Text=text,
            OutputFormat='mp3',
            VoiceId=voice_id,
            Engine=engine_type
        )

        audio_stream = response['AudioStream'].read()

        # Upload audio to S3
        s3.put_object(
            Bucket=CACHE_BUCKET,
            Key=s3_key,
            Body=audio_stream,
            ContentType='audio/mpeg',
            ACL='bucket-owner-full-control'
        )

        # Publish notification to SNS
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject='New TTS Audio Created',
            Message=(
                f"Voice used: {voice_id}\n"
                f"Snippet: {text[:100]}...\n"
                f"S3 Object: {s3_key}\n"
                f"Generated at: {datetime.utcnow().isoformat()} UTC"
            )
        )

        # Generate pre-signed URL
        presigned_url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': CACHE_BUCKET, 'Key': s3_key},
            ExpiresIn=3600
        )

        return _success(presigned_url)

    except Exception as e:
        return _error(500, str(e))


def _success(url):
    return {
        "statusCode": 200,
        "headers": _cors_headers(),
        "body": json.dumps({ "downloadUrl": url })
    }

def _error(code, message):
    return {
        "statusCode": code,
        "headers": _cors_headers(),
        "body": json.dumps({ "error": message })
    }

def _cors_headers():
    return {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "https://sedky.net",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Allow-Methods": "POST"
    }