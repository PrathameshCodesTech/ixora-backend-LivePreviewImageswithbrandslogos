from celery import shared_task
import os
import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def generate_image_async(self, template_id, doctor_id, content_data, selected_brand_ids=None):
    """Generate image in background - IMAGE ONLY with improved error handling"""
    import psutil
    import gc
    
    logger.info(f"TASK DEBUG: Using updated task code with selected_brand_ids: {selected_brand_ids}")
    # Check system resources before starting
    memory_percent = psutil.virtual_memory().percent
    if memory_percent > 90:
        raise Exception(f"System memory too high: {memory_percent}%")
    
    try:
        from .views import GenerateImageContentView
        from .models import VideoTemplates, DoctorVideo, ImageContent
        from django.core.files import File
        
        # Log task start
        logger.info(f"Starting image generation task for template {template_id}, doctor {doctor_id}")
        
        template = VideoTemplates.objects.get(id=template_id, template_type='image')
        doctor = DoctorVideo.objects.get(id=doctor_id)
        
        # Generate image with memory monitoring
        image_gen = GenerateImageContentView()
        output_path = image_gen.generate_image_with_text(
            template, content_data, doctor, selected_brand_ids
        )
        
        # Save to database
        image_content = ImageContent.objects.create(
            template=template,
            doctor=doctor,
            content_data=content_data
        )
        
        with open(output_path, 'rb') as f:
            image_content.output_image.save(f"generated_{image_content.id}.png", File(f), save=True)
        
        # Clean up file
        try:
            os.remove(output_path)
        except OSError:
            pass
        
        logger.info(f"Successfully completed image generation for task {self.request.id}")
        return {
            "status": "success", 
            "image_id": image_content.id,
            "doctor_name": doctor.name
        }
        
    except (VideoTemplates.DoesNotExist, DoctorVideo.DoesNotExist) as e:
        logger.error(f"Database record not found: {e}")
        raise  # Don't retry for missing records
    except MemoryError as e:
        logger.error(f"Memory error during image generation: {e}")
        gc.collect()  # Force cleanup
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=120, exc=e)  # Retry after 2 minutes
        raise
    except Exception as e:
        logger.error(f"Image generation failed: {e}", exc_info=True)
        
        # Check if it's a resource issue
        memory_percent = psutil.virtual_memory().percent
        if memory_percent > 85:
            logger.error(f"High memory usage detected: {memory_percent}%")
            gc.collect()
            
        if self.request.retries < self.max_retries:
            countdown = 60 * (self.request.retries + 1)
            logger.info(f"Retrying image generation (attempt {self.request.retries + 1}) in {countdown}s")
            raise self.retry(countdown=countdown, exc=e)
        else:
            logger.error("Max retries exceeded for image generation")
            raise
    finally:
        # Force garbage collection after each task
        gc.collect()
        logger.info(f"Completed cleanup for task {self.request.id}")